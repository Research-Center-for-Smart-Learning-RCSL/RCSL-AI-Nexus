//! gemma4's tokenizer, as the runtime actually runs it (C6b on #24).
//!
//! Ollama 0.33.2 serves gemma4 through llama.cpp b10630, whose Ollama
//! compatibility layer rewrites `tokenizer.ggml.model` from `"llama"` to
//! `"gemma4"`: llama.cpp's BPE with the `gemma4` pre-tokenizer, not
//! SentencePiece. This is a port of that path from `src/llama-vocab.cpp`; the
//! reasoning, step by step, is in the Python twin
//! (`app/adapters/tokenizer/gguf_token_counter/gemma4_bpe.py`), and both are
//! held to the runtime's own token ids in `tests/unit/gemma4_tokenizer_goldens.py`.

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, HashSet};

use ahash::AHashMap;

use crate::gguf::{GgufError, GgufValue};

const CONTROL: u32 = 3;
const USER_DEFINED: u32 = 4;
const UNKNOWN: u32 = 2;
const NORMAL: u32 = 1;

const EOG_TEXTS: &[&str] = &[
    "<|eot_id|>",
    "<|im_end|>",
    "<|end|>",
    "<|return|>",
    "<|call|>",
    "<|flush|>",
    "<|calls|>",
    "<end_of_turn>",
    "<|endoftext|>",
    "</s>",
    "<|eom_id|>",
    "<EOT>",
    "_<EOT>",
    "[EOT]",
    "[EOS]",
    "<|end_of_text|>",
    "<end_of_utterance>",
    "<eos>",
    "<turn|>",
    "<|tool_response>",
    "<｜end▁of▁sentence｜>",
    "[e~[",
];
const FORCED_USER_DEFINED: &[&str] = &["<|channel|>", "<|message|>", "<|start|>", "<|constrain|>"];
const UNMODELLED: &[&str] = &["<|return|>", "<|call|>", "<|calls|>", "<|flush|>"];

pub struct Gemma4Bpe {
    ids: AHashMap<String, u32>,
    /// Keyed by `left + "\0" + right`; see `build` for why that is unambiguous.
    ranks: AHashMap<String, u32>,
    bytes: [Option<u32>; 256],
    /// `(text, id)`, longest first.
    specials: Vec<(String, u32)>,
}

impl Gemma4Bpe {
    pub fn build(metadata: &HashMap<String, GgufValue>) -> Result<Self, GgufError> {
        let tokens = metadata
            .get("tokenizer.ggml.tokens")
            .and_then(|v| v.as_string_array())
            .ok_or_else(|| GgufError("missing tokenizer.ggml.tokens".into()))?;
        let merges = metadata
            .get("tokenizer.ggml.merges")
            .and_then(|v| v.as_string_array())
            .ok_or_else(|| GgufError("missing tokenizer.ggml.merges".into()))?;
        let types: Vec<u32> = metadata
            .get("tokenizer.ggml.token_type")
            .and_then(|v| v.as_token_types())
            .unwrap_or_default();

        if tokens.iter().any(|t| UNMODELLED.contains(&t.as_str())) {
            return Err(GgufError("the vocabulary carries harmony tokens".into()));
        }
        // A NUL inside a merge would make the joined key ambiguous.
        if merges.iter().any(|m| m.contains('\0')) {
            return Err(GgufError("a merge contains NUL".into()));
        }

        let mut ids = AHashMap::with_capacity(tokens.len());
        for (i, token) in tokens.iter().enumerate() {
            ids.insert(token.clone(), i as u32); // the last duplicate wins
        }
        let mut ranks = AHashMap::with_capacity(merges.len());
        for (rank, merge) in merges.iter().enumerate() {
            // `word.find(' ', 1)`, in bytes, as llama.cpp splits it.
            // ' ' is ASCII, so the byte it is found at is a char boundary.
            let found = merge.as_bytes().iter().skip(1).position(|&b| b == b' ');
            let key = match found {
                Some(at) => format!("{}\0{}", &merge[..at + 1], &merge[at + 2..]),
                None => "\0".to_string(),
            };
            ranks.entry(key).or_insert(rank as u32); // the first duplicate wins
        }
        let mut bytes = [None; 256];
        for (b, slot) in bytes.iter_mut().enumerate() {
            *slot = ids.get(&format!("<0x{b:02X}>")).copied();
        }
        let specials = special_tokens(tokens, &types, &ids)?;
        Ok(Self {
            ids,
            ranks,
            bytes,
            specials,
        })
    }

    pub fn count(&self, text: &str) -> usize {
        let mut out = Vec::new();
        self.encode_into(text, &mut out);
        out.len()
    }

    pub fn encode_into(&self, text: &str, out: &mut Vec<u32>) {
        for (fragment, special) in self.partition(text) {
            match special {
                Some(id) => out.push(id),
                None => self.tokenize(&fragment.replace(' ', "▁"), out),
            }
        }
    }

    fn partition<'a>(&self, text: &'a str) -> Vec<(&'a str, Option<u32>)> {
        let mut fragments: Vec<(&str, Option<u32>)> = if text.is_empty() {
            Vec::new()
        } else {
            vec![(text, None)]
        };
        for (special, id) in &self.specials {
            let mut split = Vec::with_capacity(fragments.len());
            for (value, known) in fragments {
                if known.is_some() || !value.contains(special.as_str()) {
                    split.push((value, known));
                    continue;
                }
                for (i, piece) in value.split(special.as_str()).enumerate() {
                    if i > 0 {
                        split.push((&text[0..0], Some(*id)));
                    }
                    if !piece.is_empty() {
                        split.push((piece, None));
                    }
                }
            }
            fragments = split;
        }
        fragments
    }

    fn tokenize(&self, text: &str, out: &mut Vec<u32>) {
        for word in words(text) {
            if word.starts_with('\n')
                && let Some(&id) = self.ids.get(word)
            {
                out.push(id);
                continue;
            }
            for symbol in self.merge(word) {
                if let Some(&id) = self.ids.get(symbol.as_str()) {
                    out.push(id);
                } else {
                    out.extend(symbol.bytes().filter_map(|b| self.bytes[b as usize]));
                }
            }
        }
    }

    fn rank(&self, key: &mut String, left: &str, right: &str) -> Option<u32> {
        key.clear();
        key.push_str(left);
        key.push('\0');
        key.push_str(right);
        self.ranks.get(key.as_str()).copied()
    }

    fn merge(&self, word: &str) -> Vec<String> {
        let mut symbols: Vec<String> = word.chars().map(String::from).collect();
        let n = symbols.len() as isize;
        let mut next: Vec<isize> = (1..=n).collect();
        if let Some(last) = next.last_mut() {
            *last = -1;
        }
        let mut prev: Vec<isize> = (-1..n - 1).collect();
        // Lowest rank first, then leftmost: llama.cpp's `llm_bigram_bpe`.
        let mut queue: BinaryHeap<Reverse<(u32, usize, usize, String)>> = BinaryHeap::new();
        let mut key = String::new();

        let push = |queue: &mut BinaryHeap<Reverse<(u32, usize, usize, String)>>,
                    symbols: &Vec<String>,
                    key: &mut String,
                    left: isize,
                    right: isize| {
            if left < 0 || right < 0 {
                return;
            }
            let (l, r) = (&symbols[left as usize], &symbols[right as usize]);
            if let Some(rank) = self.rank(key, l, r) {
                queue.push(Reverse((
                    rank,
                    left as usize,
                    right as usize,
                    format!("{l}{r}"),
                )));
            }
        };

        for i in 1..n {
            push(&mut queue, &symbols, &mut key, i - 1, i);
        }
        while let Some(Reverse((_, left, right, text))) = queue.pop() {
            if symbols[left].is_empty()
                || symbols[right].is_empty()
                || symbols[left].len() + symbols[right].len() != text.len()
                || !text.starts_with(symbols[left].as_str())
                || !text.ends_with(symbols[right].as_str())
            {
                continue;
            }
            symbols[left] = text;
            symbols[right] = String::new();
            next[left] = next[right];
            if next[right] >= 0 {
                prev[next[right] as usize] = left as isize;
            }
            let (p, nx) = (prev[left], next[left]);
            push(&mut queue, &symbols, &mut key, p, left as isize);
            push(&mut queue, &symbols, &mut key, left as isize, nx);
        }
        symbols.into_iter().filter(|s| !s.is_empty()).collect()
    }
}

/// Runs of non-newlines and runs of newlines: the `[^\n]+|[\n]+` split.
fn words(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let bytes = text.as_bytes();
    for i in 1..=bytes.len() {
        if i == bytes.len() || (bytes[i] == b'\n') != (bytes[start] == b'\n') {
            if start < i {
                out.push(&text[start..i]);
            }
            start = i;
        }
    }
    out
}

/// The tokens `tokenizer_st_partition` splits out, longest first, with ids.
fn special_tokens(
    tokens: &[String],
    types: &[u32],
    ids: &AHashMap<String, u32>,
) -> Result<Vec<(String, u32)>, GgufError> {
    Ok(special_texts(tokens, types)?
        .into_iter()
        .map(|t| {
            let id = ids[t.as_str()];
            (t, id)
        })
        .collect())
}

/// The tokens llama.cpp splits out before encoding, longest first: control,
/// user-defined and unknown types after its load-time rewrites. Shared with
/// the BPE vocabularies (`tokenizer.rs`), which llama.cpp partitions the same
/// way (PR2b on #24).
pub fn special_texts(tokens: &[String], types: &[u32]) -> Result<Vec<String>, GgufError> {
    let mut attrs: Vec<u32> = (0..tokens.len())
        .map(|i| types.get(i).copied().unwrap_or(NORMAL))
        .collect();
    let present: HashMap<&str, usize> = tokens
        .iter()
        .enumerate()
        .map(|(i, t)| (t.as_str(), i))
        .collect();
    for text in EOG_TEXTS {
        if let Some(&i) = present.get(text) {
            attrs[i] = CONTROL;
        }
    }
    for text in FORCED_USER_DEFINED {
        if let Some(&i) = present.get(text) {
            attrs[i] = USER_DEFINED;
        }
    }
    if present.contains_key("<|tool_response>")
        && let Some(&i) = present.get("</s>")
    {
        attrs[i] = NORMAL;
    }
    let mut by_length: HashMap<usize, Vec<&str>> = HashMap::new();
    for (i, token) in tokens.iter().enumerate() {
        if matches!(attrs[i], CONTROL | USER_DEFINED | UNKNOWN) {
            by_length.entry(token.len()).or_default().push(token);
        }
    }
    for same in by_length.values() {
        if order_matters(same) {
            return Err(GgufError(
                "equal-length special tokens can overlap, so llama.cpp's unstable sort decides"
                    .into(),
            ));
        }
    }
    let mut lengths: Vec<usize> = by_length.keys().copied().collect();
    lengths.sort_unstable_by(|a, b| b.cmp(a));
    Ok(lengths
        .into_iter()
        .flat_map(|len| by_length[&len].iter())
        .map(|t| t.to_string())
        .collect())
}

fn order_matters(same_length: &[&str]) -> bool {
    if same_length.len() < 2 {
        return false;
    }
    let mut prefixes: HashSet<&str> = HashSet::new();
    for token in same_length {
        for (k, _) in token.char_indices().skip(1) {
            prefixes.insert(&token[..k]);
        }
    }
    same_length.iter().any(|token| {
        token
            .char_indices()
            .skip(1)
            .any(|(k, _)| prefixes.contains(&token[k..]))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vocabulary(tokens: &[&str], merges: &[&str], types: &[u32]) -> Gemma4Bpe {
        let mut metadata = HashMap::new();
        metadata.insert(
            "tokenizer.ggml.tokens".to_string(),
            GgufValue::ArrayString(tokens.iter().map(|s| s.to_string()).collect()),
        );
        metadata.insert(
            "tokenizer.ggml.merges".to_string(),
            GgufValue::ArrayString(merges.iter().map(|s| s.to_string()).collect()),
        );
        metadata.insert(
            "tokenizer.ggml.token_type".to_string(),
            GgufValue::ArrayU32(types.to_vec()),
        );
        Gemma4Bpe::build(&metadata).expect("builds")
    }

    /// The merges reach `▁a` + `bc` here, and so does the runtime; a
    /// best-split segmenter could have taken `▁ab` + `c` instead.
    #[test]
    fn merges_apply_by_rank_and_not_by_best_split() {
        let tokens = ["▁", "a", "b", "c", "▁a", "bc", "▁ab", "<eos>"];
        let bpe = vocabulary(&tokens, &["▁ a", "b c", "▁a b"], &[1, 1, 1, 1, 1, 1, 1, 3]);
        let mut out = Vec::new();
        bpe.encode_into(" abc<eos>", &mut out);
        assert_eq!(out, vec![4, 5, 7]);
    }

    #[test]
    fn a_symbol_with_no_token_falls_back_to_bytes_and_drops_what_has_none() {
        let tokens = ["a", "<0xC3>"];
        let bpe = vocabulary(&tokens, &[], &[1, 6]);
        let mut out = Vec::new();
        bpe.encode_into("aé", &mut out); // é is C3 A9; there is no <0xA9>
        assert_eq!(out, vec![0, 1]);
    }

    #[test]
    fn overlapping_specials_of_one_length_are_refused() {
        assert!(order_matters(&["<ab", "ab>"]));
        assert!(!order_matters(&["<|turn>", "<turn|>"]));
    }

    #[test]
    fn newline_runs_are_their_own_words() {
        assert_eq!(words("a\n\nb\n"), vec!["a", "\n\n", "b", "\n"]);
        assert!(words("").is_empty());
    }
}
