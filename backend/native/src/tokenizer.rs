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
    pub fn encode(&self, text: &str) -> Option<usize> {
        self.tokenizer
            .encode(text, false)
            .ok()
            .map(|encoding| encoding.get_ids().len())
    }
}

fn add_special_tokens(tokenizer: &mut Tokenizer, tokens: &[String], types: &[u32]) {
    let special: Vec<AddedToken> = tokens
        .iter()
        .zip(types.iter())
        .filter(|(_, t)| **t == CONTROL_TOKEN_TYPE)
        .map(|(token, _)| {
            let mut at = AddedToken::from(token.clone(), true);
            at = at.normalized(false);
            at
        })
        .collect();
    if !special.is_empty() {
        let _ = tokenizer.add_special_tokens(special);
    }
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
            let (left, right) = entry
                .split_once(' ')
                .ok_or_else(|| GgufError(format!("merge entry has no pair separator: {entry:?}")))?;
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

    add_special_tokens(&mut tokenizer, tokens, &types);

    Ok(tokenizer)
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

    let n = tokens.len() as f64;
    let vocab: Vec<(String, f64)> = tokens
        .iter()
        .zip(scores.iter())
        .map(|(token, &score)| {
            let s = score as f64;
            let log_prob = if n - s > 0.0 {
                ((n - s) / n).ln()
            } else {
                -100.0
            };
            (token.clone(), log_prob)
        })
        .collect();

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

    add_special_tokens(&mut tokenizer, tokens, &types);

    Ok(tokenizer)
}

pub fn build_vocabulary(
    metadata: &HashMap<String, GgufValue>,
) -> Result<Vocabulary, GgufError> {
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
