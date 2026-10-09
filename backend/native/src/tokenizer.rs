use std::collections::HashMap;

use ahash::AHashMap;
use tokenizers::models::bpe::BPE;
use tokenizers::pre_tokenizers::byte_level::ByteLevel;
use tokenizers::pre_tokenizers::sequence::Sequence;
use tokenizers::pre_tokenizers::split::{Split, SplitPattern};
use tokenizers::{AddedToken, DecoderWrapper, PreTokenizerWrapper, Tokenizer};

use crate::gemma4_bpe::Gemma4Bpe;
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

pub enum Vocabulary {
    Bpe(Box<Tokenizer>),
    Gemma4(Box<Gemma4Bpe>),
}

impl Vocabulary {
    pub fn from_tokenizer(tokenizer: Tokenizer) -> Self {
        Self::Bpe(Box::new(tokenizer))
    }

    pub fn encode(&self, text: &str) -> Option<usize> {
        match self {
            Self::Bpe(tokenizer) => tokenizer
                .encode(text, false)
                .ok()
                .map(|encoding| encoding.get_ids().len()),
            Self::Gemma4(bpe) => Some(bpe.count(text)),
        }
    }
}

/// Whether llama.cpp loads this vocabulary as gemma4's BPE: the converter's
/// `"gemma4"` model, or Ollama's `"llama"` with the `gemma4` pre-tokenizer,
/// which its compatibility layer rewrites to `"gemma4"` (see `gemma4_bpe.rs`).
pub fn is_gemma4(family: &str, scheme: &str) -> bool {
    family == GEMMA4_MODEL || (family == "llama" && scheme == "gemma4")
}

pub const GEMMA4_MODEL: &str = "gemma4";

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
        .and_then(|v| v.as_token_types())
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

pub fn build_vocabulary(metadata: &HashMap<String, GgufValue>) -> Result<Vocabulary, GgufError> {
    let family = metadata
        .get("tokenizer.ggml.model")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    let scheme = metadata
        .get("tokenizer.ggml.pre")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if family == BPE_MODEL {
        Ok(Vocabulary::Bpe(Box::new(build_bpe_tokenizer(metadata)?)))
    } else if is_gemma4(family, scheme) {
        Ok(Vocabulary::Gemma4(Box::new(Gemma4Bpe::build(metadata)?)))
    } else {
        // SentencePiece proper is not counted: Unigram can under-count it
        // (#25), and no model here is served by it to port from (C6b).
        Err(GgufError(format!(
            "tokenizer model {family:?} with pre-tokenizer {scheme:?} has no runtime-equivalent encoder"
        )))
    }
}
