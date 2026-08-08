#![cfg(any(feature = "real-audio", test))]

use hound::{WavSpec, WavWriter};
use std::fs::File;
use std::io::BufWriter;
use std::path::Path;
use std::sync::{Arc, Mutex};

pub struct AudioEncoder {
    writer: Arc<Mutex<Option<WavWriter<BufWriter<File>>>>>,
    #[allow(dead_code)]
    spec: WavSpec,
}

impl AudioEncoder {
    pub fn new<P: AsRef<Path>>(path: P, sample_rate: u32, channels: u16) -> Result<Self, String> {
        let spec = WavSpec {
            channels,
            sample_rate,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };

        let writer = WavWriter::create(path, spec)
            .map_err(|e| format!("Failed to create WAV writer: {:?}", e))?;

        Ok(Self {
            writer: Arc::new(Mutex::new(Some(writer))),
            spec,
        })
    }

    pub fn write_i16(&self, samples: &[i16]) -> Result<(), String> {
        let mut guard = self
            .writer
            .lock()
            .map_err(|_| "encoder writer mutex poisoned".to_string())?;
        let writer = guard
            .as_mut()
            .ok_or_else(|| "encoder writer already finalized".to_string())?;
        for &sample in samples {
            writer
                .write_sample(sample)
                .map_err(|e| format!("Failed to write sample: {:?}", e))?;
        }
        Ok(())
    }

    pub fn finalize(&self) -> Result<(), String> {
        let mut guard = self
            .writer
            .lock()
            .map_err(|_| "encoder writer mutex poisoned".to_string())?;
        let writer = guard
            .take()
            .ok_or_else(|| "encoder writer already finalized".to_string())?;
        writer
            .finalize()
            .map_err(|e| format!("Failed to finalize WAV file: {:?}", e))
    }

    #[cfg(test)]
    pub fn writer_arc(&self) -> Arc<Mutex<Option<WavWriter<BufWriter<File>>>>> {
        self.writer.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_ID: AtomicU64 = AtomicU64::new(0);

    fn test_path(ext: &str) -> std::path::PathBuf {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        std::env::temp_dir().join(format!("quinoa_audio_encoder_test_{}_{}", id, ext))
    }

    #[test]
    fn test_write_finalize_and_spec() {
        let path = test_path("spec.wav");
        let _ = std::fs::remove_file(&path);
        let enc = AudioEncoder::new(&path, 48000, 1).unwrap();
        enc.write_i16(&[0i16, 1000, -1000, 32767, -32768]).unwrap();
        enc.finalize().unwrap();

        let reader = hound::WavReader::open(&path).unwrap();
        assert_eq!(reader.spec().sample_rate, 48000);
        assert_eq!(reader.spec().channels, 1);
        assert_eq!(reader.len() as usize, 5);
    }

    #[test]
    fn test_write_after_finalize_fails() {
        let path = test_path("finalize_once.wav");
        let _ = std::fs::remove_file(&path);
        let enc = AudioEncoder::new(&path, 44100, 1).unwrap();
        enc.finalize().unwrap();
        let err = enc.write_i16(&[0]).unwrap_err();
        assert!(err.contains("finalized"), "unexpected error: {}", err);
    }

    #[test]
    fn test_poisoned_writer_returns_error() {
        let path = test_path("poison.wav");
        let _ = std::fs::remove_file(&path);
        let enc = AudioEncoder::new(&path, 48000, 1).unwrap();
        let writer = enc.writer_arc();
        let handle = std::thread::spawn(move || {
            let _guard = writer.lock().unwrap();
            panic!("intentional poison");
        });
        let _ = handle.join();
        let err = enc.write_i16(&[0]).unwrap_err();
        assert!(err.contains("poisoned"), "unexpected error: {}", err);
        let err = enc.finalize().unwrap_err();
        assert!(err.contains("poisoned"), "unexpected error: {}", err);
    }
}
