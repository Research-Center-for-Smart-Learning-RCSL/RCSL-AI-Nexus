use std::collections::HashMap;

use ahash::AHashMap;
use tokenizers::models::bpe::BPE;
use tokenizers::models::unigram::Unigram;
use tokenizers::pre_tokenizers::byte_level::ByteLevel;
use tokenizers::pre_tokenizers::metaspace::Metaspace;
use tokenizers::pre_tokenizers::sequence::Sequence;
use tokenizers::pre_tokenizers::split::{Split, SplitPattern};
use tokenizers::{AddedToken, DecoderWrapper, PreTokenizerWrapper, Tokenizer};

use crate::gguf::{GgufError, GgufValue};

const CONTROL_TOKEN_TYPE: u32 = 3;
pub const BPE_MODEL: &str = "gpt2";

const PRE_TOKENIZER_PATTERN: &str = concat!(
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)",
    r"|[^\r\n\p{L}\p{N}]?\p{L}+",
    r"|\p{N}",
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*",
    r"|\s*[\r\n]+",
    r"|\s+(?!\S)",
    r"|\s+",
);

pub struct Vocabulary {
    tokenizer: Tokenizer,
}

impl Vocabulary {
    pub fn from_tokenizer(tokenizer: Tokenizer) -> Self {
        Self { tokenizer }
    }

    pub fn encode(&self, text: &str) -> Option<usize> {
        self.tokenizer
            .encode(text, false)
            .ok()
            .map(|encoding| encoding.get_ids().len())
    }
}

fn add_special_tokens(
    tokenizer: &mut Tokenizer,
    tokens: &[String],
    types: &[u32],
) -> Result<(), GgufError> {
    let special: Vec<AddedToken> = tokens
        .iter()
        .zip(types.iter())
        .filter(|(_, t)| **t == CONTROL_TOKEN_TYPE)
        .map(|(token, _)| {
            AddedToken::from(token.clone(), true)
                .normalized(false)
                .single_word(false)
        })
        .collect();
    if !special.is_empty() {
        tokenizer
            .add_special_tokens(special)
            .map_err(|e| GgufError(format!("failed to add special tokens: {e}")))?;
    }
    Ok(())
}

fn build_bpe_tokenizer(metadata: &HashMap<String, GgufValue>) -> Result<Tokenizer, GgufError> {
    let tokens = metadata
        .get("tokenizer.ggml.tokens")
        .and_then(|v| v.as_string_array())
        .ok_or_else(|| GgufError("missing tokenizer.ggml.tokens".into()))?;

    let merges_raw = metadata
        .get("tokenizer.ggml.merges")
        .and_then(|v| v.as_string_array())
        .ok_or_else(|| GgufError("missing tokenizer.ggml.merges".into()))?;

    let types: Vec<u32> = metadata
        .get("tokenizer.ggml.token_type")
        .and_then(|v| v.as_u32_array())
        .map(|v| v.to_vec())
        .unwrap_or_default();

    let vocab: AHashMap<String, u32> = tokens
        .iter()
        .enumerate()
        .map(|(i, t)| (t.clone(), i as u32))
        .collect();

    let merges: Vec<(String, String)> = merges_raw
        .iter()
        .map(|entry| {
            let (left, right) = entry.split_once(' ').ok_or_else(|| {
                GgufError(format!("merge entry has no pair separator: {entry:?}"))
            })?;
            Ok((left.to_string(), right.to_string()))
        })
        .collect::<Result<Vec<_>, GgufError>>()?;

    let bpe = BPE::builder()
        .vocab_and_merges(vocab, merges)
        .fuse_unk(false)
        .byte_fallback(false)
        .build()
        .map_err(|e| GgufError(format!("failed to build BPE: {e}")))?;

    let mut tokenizer = Tokenizer::new(bpe);

    let split = Split::new(
        SplitPattern::Regex(PRE_TOKENIZER_PATTERN.to_string()),
        tokenizers::SplitDelimiterBehavior::Isolated,
        false,
    )
    .map_err(|e| GgufError(format!("failed to build split pre-tokenizer: {e}")))?;

    let byte_level = ByteLevel::new(false, false, false);

    tokenizer.with_pre_tokenizer(Some(Sequence::new(vec![
        PreTokenizerWrapper::Split(split),
        PreTokenizerWrapper::ByteLevel(byte_level),
    ])));

    tokenizer.with_decoder(Some(DecoderWrapper::ByteLevel(ByteLevel::new(
        false, false, false,
    ))));

    add_special_tokens(&mut tokenizer, tokens, &types)?;

    Ok(tokenizer)
}

/// Convert a GGUF `scores` array into log-probabilities Unigram can segment with.
///
/// The array means two different things depending on who wrote the file, and
/// both arrive under `tokenizer.ggml.model = "llama"`, so the convention is
/// detected rather than assumed. Read from the deployment on 2026-09-07:
/// `gemma4:31b-it-q8_0` carries ordinal ranks 0.0 to 262143.0, `gemma4:31b-it-qat`
/// and `nomic-embed-text` carry -1000.0 in every entry as a placeholder, and
/// llama-2, Mistral and anything converted from real SentencePiece carry
/// genuine negative log-probabilities.
///
/// Non-negative means ranks, and they are remapped: Unigram maximises the *sum*
/// over a split, so what decides whether a word stays one token is the size of
/// the gaps rather than their order. `((n - s) / n).ln()` was used until
/// 2026-09-07 and crushes the vocabulary against zero — rank 1000 at -0.0038 —
/// so extra tokens cost nothing and words were split. Measured 2.04x over the
/// runtime's own `prompt_eval_count` on gemma4; `-ln(rank + 1)` is 1.01x.
///
/// Negative and varying means log-probabilities already, and they pass through.
/// A clamp here would be worse than the crash it avoids: it maps every real
/// log-probability to one value, which is the uniform vocabulary this function
/// exists to prevent.
///
/// All equal means no information, and that is an error rather than a guess, so
/// the caller falls back to the character estimate instead of segmenting from a
/// vocabulary that cannot rank anything.
///
/// Kept in step with `construction.scores_to_log_probabilities` on the Python
/// side, which carries the same measurements.
fn scores_to_log_probabilities(scores: &[f32]) -> Result<Vec<f64>, GgufError> {
    let first = *scores
        .first()
        .ok_or_else(|| GgufError("the vocabulary carries no scores".into()))?;
    if scores.iter().all(|&s| s == first) {
        return Err(GgufError(format!(
            "every score is {first}, which is a placeholder rather than a distribution"
        )));
    }
    if scores.iter().any(|&s| s < 0.0) {
        return Ok(scores.iter().map(|&s| s as f64).collect());
    }
    Ok(scores.iter().map(|&s| -((s as f64) + 1.0).ln()).collect())
}

fn build_unigram_tokenizer(metadata: &HashMap<String, GgufValue>) -> Result<Tokenizer, GgufError> {
    let tokens = metadata
        .get("tokenizer.ggml.tokens")
        .and_then(|v| v.as_string_array())
        .ok_or_else(|| GgufError("missing tokenizer.ggml.tokens".into()))?;

    let scores = metadata
        .get("tokenizer.ggml.scores")
        .and_then(|v| v.as_f32_array())
        .ok_or_else(|| GgufError("missing tokenizer.ggml.scores".into()))?;

    let types: Vec<u32> = metadata
        .get("tokenizer.ggml.token_type")
        .and_then(|v| v.as_u32_array())
        .map(|v| v.to_vec())
        .unwrap_or_default();

    let log_probs = scores_to_log_probabilities(scores)?;
    let vocab: Vec<(String, f64)> = tokens.iter().cloned().zip(log_probs).collect();

    let unigram = Unigram::from(vocab, None, false)
        .map_err(|e| GgufError(format!("failed to build Unigram: {e}")))?;

    let mut tokenizer = Tokenizer::new(unigram);

    let metaspace = Metaspace::new(
        '▁',
        tokenizers::pre_tokenizers::metaspace::PrependScheme::Always,
        true,
    );
    tokenizer.with_pre_tokenizer(Some(PreTokenizerWrapper::Metaspace(metaspace.clone())));
    tokenizer.with_decoder(Some(DecoderWrapper::Metaspace(metaspace)));

    add_special_tokens(&mut tokenizer, tokens, &types)?;

    Ok(tokenizer)
}

pub fn build_vocabulary(metadata: &HashMap<String, GgufValue>) -> Result<Vocabulary, GgufError> {
    let family = metadata
        .get("tokenizer.ggml.model")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let tokenizer = if family == BPE_MODEL {
        build_bpe_tokenizer(metadata)?
    } else {
        build_unigram_tokenizer(metadata)?
    };

    Ok(Vocabulary { tokenizer })
}

#[cfg(test)]
mod tests {
    use super::scores_to_log_probabilities;

    /// The property the old mapping lost, and the reason this file has a test
    /// at all: the Rust and Python vocabularies were held in step by a comment,
    /// which is how a twofold counting error survived in both at once.
    #[test]
    fn ranks_are_spread_far_enough_to_prefer_whole_words() {
        let scores: Vec<f32> = (0..30_000).map(|i| i as f32).collect();
        let got = scores_to_log_probabilities(&scores).expect("ranks are usable");

        assert!(got[1_000] > got[20_000]);
        // Nats. The old `((n - s) / n).ln()` put this gap at 0.08.
        assert!(
            got[1_000] - got[20_000] > 2.0,
            "gap was {}",
            got[1_000] - got[20_000]
        );
        assert!(got.iter().all(|v| v.is_finite()));
    }

    /// A real SentencePiece vocabulary. `-ln(score + 1)` on -12.5 is the
    /// logarithm of a negative number: NaN here, which `Unigram::from` accepts
    /// and then segments character by character.
    #[test]
    fn real_log_probabilities_pass_through_untouched() {
        let scores = [-1.5f32, -12.5, -3.25];
        let got = scores_to_log_probabilities(&scores).expect("log-probabilities are usable");

        assert_eq!(got, vec![-1.5f64, -12.5, -3.25]);
        assert!(got.iter().all(|v| v.is_finite()));
    }

    /// `gemma4:31b-it-qat` and `nomic-embed-text` both carry this. Refusing
    /// sends the caller to the character estimate; guessing would send it to a
    /// uniform vocabulary, which is the failure being fixed.
    #[test]
    fn a_constant_placeholder_is_refused_rather_than_guessed_at() {
        assert!(scores_to_log_probabilities(&[-1000.0f32; 8]).is_err());
        assert!(scores_to_log_probabilities(&[]).is_err());
    }
}
