use pyo3::prelude::*;

#[cfg(feature = "real-audio")]
mod device;
mod capture;

use capture::session::{start_recording_impl, RecordingConfig, RecordingSession, AudioEvent};

#[derive(Clone, Debug, PartialEq)]
#[pyclass(eq, eq_int)]
pub enum DeviceType {
    Microphone,
    Speaker,
    Monitor,
}

#[derive(Clone, Debug)]
#[pyclass]
pub struct Device {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub device_type: DeviceType,
    #[pyo3(get)]
    pub is_bluetooth: bool,
    #[pyo3(get)]
    pub sample_rate: u32,
    #[pyo3(get)]
    pub channels: u8,
    #[pyo3(get)]
    pub is_default: bool,
}

#[pymethods]
impl Device {
    #[new]
    fn new(
        id: String,
        name: String,
        device_type: DeviceType,
        is_bluetooth: bool,
        sample_rate: u32,
        channels: u8,
        is_default: bool,
    ) -> Self {
        Device {
            id,
            name,
            device_type,
            is_bluetooth,
            sample_rate,
            channels,
            is_default,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Device(id='{}', name='{}', type={:?})",
            self.id, self.name, self.device_type
        )
    }
}

#[pyfunction]
fn list_devices() -> PyResult<Vec<Device>> {
    #[cfg(feature = "real-audio")]
    {
        device::enumerate::list_devices_pw()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    #[cfg(not(feature = "real-audio"))]
    {
        // Mock implementation
        Ok(vec![
            Device {
                id: "mock_mic_1".to_string(),
                name: "Mock Microphone".to_string(),
                device_type: DeviceType::Microphone,
                is_bluetooth: false,
                sample_rate: 48000,
                channels: 1,
                is_default: true,
            },
            Device {
                id: "mock_speaker_1".to_string(),
                name: "Mock Speakers".to_string(),
                device_type: DeviceType::Speaker,
                is_bluetooth: false,
                sample_rate: 48000,
                channels: 2,
                is_default: true,
            },
            Device {
                id: "mock_bt_headset".to_string(),
                name: "Mock Bluetooth Headset".to_string(),
                device_type: DeviceType::Microphone,
                is_bluetooth: true,
                sample_rate: 16000,
                channels: 1,
                is_default: false,
            },
        ])
    }
}

#[pyfunction]
fn start_recording(config: RecordingConfig) -> PyResult<RecordingSession> {
    start_recording_impl(config)
}

/// A Python module implemented in Rust.
#[pymodule]
fn granola_audio(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Device>()?;
    m.add_class::<DeviceType>()?;
    m.add_class::<RecordingConfig>()?;
    m.add_class::<RecordingSession>()?;
    m.add_class::<AudioEvent>()?;
    m.add_function(wrap_pyfunction!(list_devices, m)?)?;
    m.add_function(wrap_pyfunction!(start_recording, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_device_creation() {
        let device = Device::new(
            "test_id".to_string(),
            "Test Device".to_string(),
            DeviceType::Microphone,
            true,
            48000,
            2,
            false,
        );

        assert_eq!(device.id, "test_id");
        assert_eq!(device.name, "Test Device");
        assert_eq!(device.device_type, DeviceType::Microphone);
        assert!(device.is_bluetooth);
        assert_eq!(device.sample_rate, 48000);
        assert_eq!(device.channels, 2);
        assert!(!device.is_default);
    }
}
