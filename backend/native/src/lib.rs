mod gguf;
mod template;
mod tokenizer;

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

use crate::gguf::GgufValue;

struct CachedModel {
    vocabulary: tokenizer::Vocabulary,
    template: template::ChatTemplate,
}

struct BoundedCache {
    entries: HashMap<String, Option<CachedModel>>,
    order: VecDeque<String>,
    max_size: usize,
}

impl BoundedCache {
    fn new(max_size: usize) -> Self {
        Self {
            entries: HashMap::new(),
            order: VecDeque::new(),
            max_size: max_size.max(1),
        }
    }

    fn get(&self, key: &str) -> Option<&Option<CachedModel>> {
        self.entries.get(key)
    }

    fn insert(&mut self, key: String, value: Option<CachedModel>) {
        if self.entries.contains_key(&key) {
            self.order.retain(|k| k != &key);
        }
        self.entries.insert(key.clone(), value);
        self.order.push_back(key);
        while self.entries.len() > self.max_size {
            if let Some(evicted) = self.order.pop_front() {
                self.entries.remove(&evicted);
            }
        }
    }

    fn remove(&mut self, key: &str) {
        self.entries.remove(key);
        self.order.retain(|k| k != key);
    }
}

static CACHE: std::sync::LazyLock<Mutex<BoundedCache>> =
    std::sync::LazyLock::new(|| Mutex::new(BoundedCache::new(8)));

const WANTED_KEYS: &[&str] = &[
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.scores",
    "tokenizer.ggml.token_type",
    "tokenizer.ggml.pre",
    "tokenizer.ggml.model",
];
const CHAT_TEMPLATE_KEY: &str = "tokenizer.chat_template";

const KNOWN_PRE_TOKENIZERS: &[&str] = &["qwen2", "qwen35", "gemma4"];
const KNOWN_MODELS: &[&str] = &["gpt2", "llama"];

const BPE_REQUIRED: &[&str] = &["tokenizer.ggml.tokens", "tokenizer.ggml.merges"];
const UNIGRAM_REQUIRED: &[&str] = &["tokenizer.ggml.tokens", "tokenizer.ggml.scores"];

fn wanted(key: &str) -> bool {
    WANTED_KEYS.contains(&key) || key == CHAT_TEMPLATE_KEY
}

fn build(blob_path: &str) -> Result<CachedModel, String> {
    let path = std::path::Path::new(blob_path);
    let metadata = gguf::read_metadata(path, &wanted).map_err(|e| e.0)?;

    let scheme = metadata
        .get("tokenizer.ggml.pre")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if !KNOWN_PRE_TOKENIZERS.contains(&scheme) {
        return Err(format!(
            "pre-tokenizer {scheme:?} has not been measured against this platform's pattern"
        ));
    }

    let family = metadata
        .get("tokenizer.ggml.model")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if !KNOWN_MODELS.contains(&family) {
        return Err(format!(
            "tokenizer model {family:?} is not one of {:?}",
            KNOWN_MODELS
        ));
    }

    let required = if family == tokenizer::BPE_MODEL {
        BPE_REQUIRED
    } else {
        UNIGRAM_REQUIRED
    };
    let missing: Vec<&str> = required
        .iter()
        .filter(|k| !metadata.contains_key(**k))
        .copied()
        .collect();
    if !missing.is_empty() {
        return Err(format!("missing required keys: {missing:?}"));
    }

    let vocabulary = tokenizer::build_vocabulary(&metadata).map_err(|e| e.0)?;
    let template_source = metadata.get(CHAT_TEMPLATE_KEY).and_then(|v| v.as_str());
    let template = template::ChatTemplate::new(template_source).map_err(|e| e.0)?;

    Ok(CachedModel {
        vocabulary,
        template,
    })
}

fn with_cached_model<T>(
    blob_path: &str,
    cache_key: &str,
    f: impl FnOnce(Option<&CachedModel>) -> T,
) -> PyResult<T> {
    let mut cache = CACHE
        .lock()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

    if let Some(entry) = cache.get(cache_key) {
        return Ok(f(entry.as_ref()));
    }

    let built = build(blob_path).ok();
    let result = f(built.as_ref());
    cache.insert(cache_key.to_string(), built);
    Ok(result)
}

/// Prepare the tokenizer for a model reference. Returns True if the vocabulary
/// was built successfully. Returns the error message as a string on failure
/// (rather than discarding it) so the caller can log it.
#[pyfunction]
fn prepare(blob_path: String, cache_key: String) -> PyResult<(bool, Option<String>)> {
    let mut cache = CACHE
        .lock()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    cache.remove(&cache_key);

    let result = build(&blob_path);
    let (success, error) = match &result {
        Ok(_) => (true, None),
        Err(msg) => (false, Some(msg.clone())),
    };
    cache.insert(cache_key, result.ok());
    Ok((success, error))
}

/// Prepare the tokenizer from a serialized JSON string (produced by
/// `tokenizers.Tokenizer.to_str()` in Python). This guarantees identical
/// tokenization since the same constructed tokenizer object is shared.
#[pyfunction]
fn prepare_from_json(tokenizer_json: String, cache_key: String) -> PyResult<(bool, Option<String>)> {
    let mut cache = CACHE
        .lock()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    cache.remove(&cache_key);

    let result = tokenizers::Tokenizer::from_bytes(tokenizer_json.as_bytes())
        .map(|t| CachedModel {
            vocabulary: tokenizer::Vocabulary::from_tokenizer(t),
            template: template::ChatTemplate::new(None).unwrap(),
        })
        .map_err(|e| format!("failed to load tokenizer from JSON: {e}"));

    let (success, error) = match &result {
        Ok(_) => (true, None),
        Err(msg) => (false, Some(msg.clone())),
    };
    cache.insert(cache_key, result.ok());
    Ok((success, error))
}

/// Count the tokens in a rendered prompt. Returns None if the vocabulary is
/// not available or the template cannot render the messages.
#[pyfunction]
fn count_prompt(
    blob_path: String,
    cache_key: String,
    messages_json: String,
    tools_json: String,
) -> PyResult<Option<usize>> {
    with_cached_model(&blob_path, &cache_key, |model| {
        let model = model?;

        let messages: Vec<serde_json::Value> = serde_json::from_str(&messages_json).ok()?;
        let tools: Vec<serde_json::Value> = serde_json::from_str(&tools_json).ok()?;

        let rendered = model.template.render(&messages, &tools).ok()?;
        model.vocabulary.encode(&rendered)
    })
}

/// Count tokens for each text individually. Returns None if vocabulary is
/// not available.
#[pyfunction]
fn count_parts(
    blob_path: String,
    cache_key: String,
    texts: Vec<String>,
) -> PyResult<Option<Vec<usize>>> {
    with_cached_model(&blob_path, &cache_key, |model| {
        let model = model?;
        let counts: Option<Vec<usize>> = texts.iter().map(|t| model.vocabulary.encode(t)).collect();
        counts
    })
}

/// Encode pre-rendered text and return token count. The caller is responsible
/// for template rendering (in Python Jinja2, which handles all templates);
/// this function only tokenizes.
#[pyfunction]
fn encode_text(
    blob_path: String,
    cache_key: String,
    text: String,
) -> PyResult<Option<usize>> {
    with_cached_model(&blob_path, &cache_key, |model| {
        let model = model?;
        model.vocabulary.encode(&text)
    })
}

/// Encode each text individually and return counts.
#[pyfunction]
fn encode_texts(
    blob_path: String,
    cache_key: String,
    texts: Vec<String>,
) -> PyResult<Option<Vec<usize>>> {
    with_cached_model(&blob_path, &cache_key, |model| {
        let model = model?;
        texts.iter().map(|t| model.vocabulary.encode(t)).collect()
    })
}

/// Clear the cached vocabulary for a reference.
#[pyfunction]
fn evict(cache_key: String) -> PyResult<()> {
    let mut cache = CACHE
        .lock()
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    cache.remove(&cache_key);
    Ok(())
}

/// Read GGUF metadata for a file. Returns a dict. Mostly useful for testing.
#[pyfunction]
fn read_gguf_metadata(path: String) -> PyResult<HashMap<String, PyObject>> {
    let metadata = gguf::read_metadata(std::path::Path::new(&path), &|_| true)
        .map_err(|e| PyRuntimeError::new_err(e.0))?;

    Python::with_gil(|py| {
        let mut result = HashMap::new();
        for (key, value) in metadata {
            let py_val = gguf_value_to_py(py, &value)?;
            result.insert(key, py_val);
        }
        Ok(result)
    })
}

fn gguf_value_to_py(py: Python<'_>, value: &GgufValue) -> PyResult<PyObject> {
    match value {
        GgufValue::U8(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::I8(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::U16(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::I16(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::U32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::I32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::F32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::Bool(v) => Ok(v.into_pyobject(py)?.to_owned().into_any().unbind()),
        GgufValue::U64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::I64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::F64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::String(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayString(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayU32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayI32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayF32(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayU8(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayI8(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayU16(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayI16(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayBool(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayU64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayI64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
        GgufValue::ArrayF64(v) => Ok(v.into_pyobject(py)?.into_any().unbind()),
    }
}

#[pymodule]
fn nexus_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(prepare, m)?)?;
    m.add_function(wrap_pyfunction!(count_prompt, m)?)?;
    m.add_function(wrap_pyfunction!(count_parts, m)?)?;
    m.add_function(wrap_pyfunction!(prepare_from_json, m)?)?;
    m.add_function(wrap_pyfunction!(encode_text, m)?)?;
    m.add_function(wrap_pyfunction!(encode_texts, m)?)?;
    m.add_function(wrap_pyfunction!(evict, m)?)?;
    m.add_function(wrap_pyfunction!(read_gguf_metadata, m)?)?;
    Ok(())
}
