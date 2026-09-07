use minijinja::{Environment, Value};

use crate::gguf::GgufError;

/// The template used when a GGUF carries none of its own.
///
/// The tools block is not decoration. This iterated `messages` alone until
/// 2026-09-07, so on `gemma4:31b-it-q8_0` — which carries a template of zero
/// characters and serves `chat` and `code` — every tool definition counted as
/// nothing: 29 tokens for none, 29 for twelve, 29 for thirty-six, against
/// `qwen2.5:7b`'s 57 / 1,395 / 3,915. An under-count is the direction that
/// admits a prompt the runtime then truncates in silence.
///
/// Name, description and parameter schema, because that is what a runtime puts
/// in front of a model for a tool and because it measures closest: 6,748
/// against the runtime's own 6,607 for a twelve-tool payload, where the
/// tool-less fallback read 5,723 and rendering the whole OpenAI-shaped object
/// reaches 6,977. Over by 2%, which is the safe direction for a figure that
/// decides whether a prompt is refused.
///
/// Kept byte-identical to `_CHATML_FALLBACK` on the Python side. The two
/// tokenizer implementations carried the same defect at once earlier today
/// because they were held in step by a comment alone.
const CHATML_FALLBACK: &str = concat!(
    "{% if tools %}<|im_start|>system\n",
    "{% for t in tools %}",
    "{{ t.function.name }}: {{ t.function.description }}\n",
    "{{ t.function.parameters | tojson }}\n",
    "{% endfor %}",
    "<|im_end|>\n{% endif %}",
    "{% for message in messages %}",
    "<|im_start|>{{ message.role }}\n{{ message.content }}<|im_end|>\n",
    "{% endfor %}",
    "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}",
);

pub struct ChatTemplate {
    env: Environment<'static>,
}

fn tojson_filter(_state: &minijinja::State, value: Value) -> Result<String, minijinja::Error> {
    let serialized = serde_json::to_string(&value).unwrap_or_else(|_| "null".to_string());
    Ok(serialized)
}

fn raise_exception(message: String) -> Result<Value, minijinja::Error> {
    Err(minijinja::Error::new(
        minijinja::ErrorKind::InvalidOperation,
        message,
    ))
}

impl ChatTemplate {
    pub fn new(source: Option<&str>) -> Result<Self, GgufError> {
        let mut env = Environment::new();
        env.add_filter("tojson", tojson_filter);
        env.add_function("raise_exception", raise_exception);
        env.set_keep_trailing_newline(true);

        let template_source = source.unwrap_or(CHATML_FALLBACK);
        env.add_template_owned("chat".to_string(), template_source.to_string())
            .map_err(|e| GgufError(format!("template parse error: {e}")))?;

        Ok(Self { env })
    }

    pub fn render(
        &self,
        messages: &[serde_json::Value],
        tools: &[serde_json::Value],
    ) -> Result<String, GgufError> {
        let tmpl = self
            .env
            .get_template("chat")
            .map_err(|e| GgufError(format!("template lookup error: {e}")))?;

        let tools_value = if tools.is_empty() {
            Value::UNDEFINED
        } else {
            Value::from_serialize(tools)
        };

        let rendered = tmpl
            .render(minijinja::context! {
                messages => Value::from_serialize(messages),
                tools => tools_value,
                add_generation_prompt => true,
            })
            .map_err(|e| GgufError(format!("template render error: {e}")))?;

        Ok(rendered)
    }
}
