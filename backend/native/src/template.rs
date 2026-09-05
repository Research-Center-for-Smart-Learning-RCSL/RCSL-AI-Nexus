use minijinja::{Environment, Value};

use crate::gguf::GgufError;

const CHATML_FALLBACK: &str = concat!(
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
