use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

const MAGIC: &[u8; 4] = b"GGUF";
const SUPPORTED_VERSIONS: &[u32] = &[2, 3];

const MAX_KV_COUNT: u64 = 4096;
const MAX_STRING_BYTES: u64 = 8 * 1024 * 1024;
const MAX_ARRAY_LENGTH: u64 = 8_000_000;

const TYPE_STRING: u32 = 8;
const TYPE_ARRAY: u32 = 9;

#[derive(Debug, Clone)]
pub enum GgufValue {
    U8(u8),
    I8(i8),
    U16(u16),
    I16(i16),
    U32(u32),
    I32(i32),
    F32(f32),
    Bool(bool),
    U64(u64),
    I64(i64),
    F64(f64),
    String(String),
    ArrayU8(Vec<u8>),
    ArrayI8(Vec<i8>),
    ArrayU16(Vec<u16>),
    ArrayI16(Vec<i16>),
    ArrayU32(Vec<u32>),
    ArrayI32(Vec<i32>),
    ArrayF32(Vec<f32>),
    ArrayBool(Vec<bool>),
    ArrayU64(Vec<u64>),
    ArrayI64(Vec<i64>),
    ArrayF64(Vec<f64>),
    ArrayString(Vec<String>),
}

impl GgufValue {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            GgufValue::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_string_array(&self) -> Option<&[String]> {
        match self {
            GgufValue::ArrayString(v) => Some(v),
            _ => None,
        }
    }

    pub fn as_f32_array(&self) -> Option<&[f32]> {
        match self {
            GgufValue::ArrayF32(v) => Some(v),
            _ => None,
        }
    }

    pub fn as_u32_array(&self) -> Option<&[u32]> {
        match self {
            GgufValue::ArrayU32(v) => Some(v),
            _ => None,
        }
    }
}

#[derive(Debug)]
pub struct GgufError(pub String);

impl std::fmt::Display for GgufError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for GgufError {}

impl From<io::Error> for GgufError {
    fn from(e: io::Error) -> Self {
        GgufError(format!("I/O error reading GGUF: {e}"))
    }
}

struct Reader<R: Read + Seek> {
    inner: R,
}

impl<R: Read + Seek> Reader<R> {
    fn new(inner: R) -> Self {
        Self { inner }
    }

    fn raw(&mut self, count: usize) -> Result<Vec<u8>, GgufError> {
        let mut buf = vec![0u8; count];
        self.inner.read_exact(&mut buf).map_err(|_| {
            GgufError(format!(
                "header ends before {count} expected bytes could be read"
            ))
        })?;
        Ok(buf)
    }

    fn skip(&mut self, count: u64) -> Result<(), GgufError> {
        self.inner.seek(SeekFrom::Current(count as i64))?;
        Ok(())
    }

    fn u8(&mut self) -> Result<u8, GgufError> {
        let b = self.raw(1)?;
        Ok(b[0])
    }

    fn i8(&mut self) -> Result<i8, GgufError> {
        Ok(self.u8()? as i8)
    }

    fn u16(&mut self) -> Result<u16, GgufError> {
        let b = self.raw(2)?;
        Ok(u16::from_le_bytes([b[0], b[1]]))
    }

    fn i16(&mut self) -> Result<i16, GgufError> {
        let b = self.raw(2)?;
        Ok(i16::from_le_bytes([b[0], b[1]]))
    }

    fn u32(&mut self) -> Result<u32, GgufError> {
        let b = self.raw(4)?;
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    fn i32(&mut self) -> Result<i32, GgufError> {
        let b = self.raw(4)?;
        Ok(i32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    fn f32(&mut self) -> Result<f32, GgufError> {
        let b = self.raw(4)?;
        Ok(f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    fn u64(&mut self) -> Result<u64, GgufError> {
        let b = self.raw(8)?;
        Ok(u64::from_le_bytes([
            b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
        ]))
    }

    fn i64(&mut self) -> Result<i64, GgufError> {
        let b = self.raw(8)?;
        Ok(i64::from_le_bytes([
            b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
        ]))
    }

    fn f64(&mut self) -> Result<f64, GgufError> {
        let b = self.raw(8)?;
        Ok(f64::from_le_bytes([
            b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
        ]))
    }

    fn bool(&mut self) -> Result<bool, GgufError> {
        Ok(self.u8()? != 0)
    }

    fn length(&mut self, limit: u64, what: &str) -> Result<u64, GgufError> {
        let value = self.u64()?;
        if value > limit {
            return Err(GgufError(format!(
                "{what} declares {value}, above the {limit} this reader accepts"
            )));
        }
        Ok(value)
    }

    fn string(&mut self) -> Result<String, GgufError> {
        let size = self.length(MAX_STRING_BYTES, "string")? as usize;
        let data = self.raw(size)?;
        Ok(String::from_utf8_lossy(&data).into_owned())
    }

    fn skip_string(&mut self) -> Result<(), GgufError> {
        let size = self.length(MAX_STRING_BYTES, "string")?;
        self.skip(size)
    }

    fn scalar_size(type_id: u32) -> Result<usize, GgufError> {
        match type_id {
            0 | 1 | 7 => Ok(1),
            2 | 3 => Ok(2),
            4 | 5 | 6 => Ok(4),
            10 | 11 | 12 => Ok(8),
            _ => Err(GgufError(format!("unknown scalar type {type_id}"))),
        }
    }

    fn read_scalar(&mut self, type_id: u32) -> Result<GgufValue, GgufError> {
        match type_id {
            0 => Ok(GgufValue::U8(self.u8()?)),
            1 => Ok(GgufValue::I8(self.i8()?)),
            2 => Ok(GgufValue::U16(self.u16()?)),
            3 => Ok(GgufValue::I16(self.i16()?)),
            4 => Ok(GgufValue::U32(self.u32()?)),
            5 => Ok(GgufValue::I32(self.i32()?)),
            6 => Ok(GgufValue::F32(self.f32()?)),
            7 => Ok(GgufValue::Bool(self.bool()?)),
            10 => Ok(GgufValue::U64(self.u64()?)),
            11 => Ok(GgufValue::I64(self.i64()?)),
            12 => Ok(GgufValue::F64(self.f64()?)),
            _ => Err(GgufError(format!("unknown scalar type {type_id}"))),
        }
    }

    fn read_value(&mut self, type_id: u32) -> Result<GgufValue, GgufError> {
        if type_id == TYPE_STRING {
            return Ok(GgufValue::String(self.string()?));
        }
        if type_id == TYPE_ARRAY {
            let element_type = self.u32()?;
            let count = self.length(MAX_ARRAY_LENGTH, "array")? as usize;
            return self.read_array(element_type, count);
        }
        self.read_scalar(type_id)
    }

    fn read_array(&mut self, element_type: u32, count: usize) -> Result<GgufValue, GgufError> {
        if element_type == TYPE_ARRAY {
            return Err(GgufError(
                "nested arrays are not part of the format this reader accepts".into(),
            ));
        }
        if element_type == TYPE_STRING {
            let mut v = Vec::with_capacity(count);
            for _ in 0..count {
                v.push(self.string()?);
            }
            return Ok(GgufValue::ArrayString(v));
        }
        macro_rules! read_typed_array {
            ($variant:ident, $method:ident) => {{
                let mut v = Vec::with_capacity(count);
                for _ in 0..count {
                    v.push(self.$method()?);
                }
                Ok(GgufValue::$variant(v))
            }};
        }
        match element_type {
            0 => read_typed_array!(ArrayU8, u8),
            1 => read_typed_array!(ArrayI8, i8),
            2 => read_typed_array!(ArrayU16, u16),
            3 => read_typed_array!(ArrayI16, i16),
            4 => read_typed_array!(ArrayU32, u32),
            5 => read_typed_array!(ArrayI32, i32),
            6 => read_typed_array!(ArrayF32, f32),
            7 => read_typed_array!(ArrayBool, bool),
            10 => read_typed_array!(ArrayU64, u64),
            11 => read_typed_array!(ArrayI64, i64),
            12 => read_typed_array!(ArrayF64, f64),
            _ => Err(GgufError(format!("unknown array element type {element_type}"))),
        }
    }

    fn skip_value(&mut self, type_id: u32) -> Result<(), GgufError> {
        if type_id == TYPE_STRING {
            return self.skip_string();
        }
        if type_id == TYPE_ARRAY {
            let element_type = self.u32()?;
            let count = self.length(MAX_ARRAY_LENGTH, "array")?;
            if element_type == TYPE_ARRAY {
                return Err(GgufError(
                    "nested arrays are not part of the format this reader accepts".into(),
                ));
            }
            if element_type == TYPE_STRING {
                for _ in 0..count {
                    self.skip_string()?;
                }
                return Ok(());
            }
            let size = Self::scalar_size(element_type)? as u64;
            return self.skip(size * count);
        }
        let size = Self::scalar_size(type_id)? as u64;
        self.skip(size)
    }
}

pub fn read_metadata(
    path: &Path,
    wanted: &dyn Fn(&str) -> bool,
) -> Result<HashMap<String, GgufValue>, GgufError> {
    let file = File::open(path)?;
    let mut reader = Reader::new(BufReader::new(file));

    let magic = reader.raw(4)?;
    if magic != MAGIC {
        return Err(GgufError(format!(
            "{} does not begin with the GGUF magic",
            path.display()
        )));
    }

    let version = reader.u32()?;
    if !SUPPORTED_VERSIONS.contains(&version) {
        return Err(GgufError(format!(
            "GGUF version {version} is not one this reader has been checked on"
        )));
    }

    // tensor count — skip
    reader.length(u64::from(u32::MAX), "tensor count")?;
    let pairs = reader.length(MAX_KV_COUNT, "metadata pair count")?;

    let mut found = HashMap::new();
    for _ in 0..pairs {
        let key = reader.string()?;
        let type_id = reader.u32()?;
        if wanted(&key) {
            found.insert(key, reader.read_value(type_id)?);
        } else {
            reader.skip_value(type_id)?;
        }
    }
    Ok(found)
}
