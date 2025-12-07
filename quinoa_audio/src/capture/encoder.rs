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

    pub fn write(&self, samples: &[f32]) -> Result<(), String> {
        if let Ok(mut guard) = self.writer.lock() {
            if let Some(writer) = guard.as_mut() {
                for &sample in samples {
                    // Convert f32 (-1.0 to 1.0) to i16
                    let val = (sample.clamp(-1.0, 1.0) * 32767.0) as i16;
                    writer
                        .write_sample(val)
                        .map_err(|e| format!("Failed to write sample: {:?}", e))?;
                }
            }
        }
        Ok(())
    }

    pub fn finalize(&self) -> Result<(), String> {
        if let Ok(mut guard) = self.writer.lock() {
            if let Some(writer) = guard.take() {
                writer
                    .finalize()
                    .map_err(|e| format!("Failed to finalize WAV file: {:?}", e))?;
            }
        }
        Ok(())
    }
}
