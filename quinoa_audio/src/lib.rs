use pyo3::prelude::*;

mod device;
mod capture;

use capture::session::{start_recording_impl, RecordingConfig, RecordingSession, AudioEvent};
#[cfg(feature = "real-audio")]
use device::monitor::start_monitoring;

use std::sync::mpsc::{Receiver, Sender};
use std::sync::Mutex;
use std::thread;

#[derive(Clone, Debug, PartialEq)]
#[pyclass(eq, eq_int)]
pub enum DeviceType {
    Microphone,
    Speaker,
    Monitor,
}

#[derive(Clone, Debug)]
#[pyclass]
pub struct DeviceEvent {
    #[pyo3(get)]
    pub type_: String, // "added", "removed", "default_changed"
    #[pyo3(get)]
    pub device_id: Option<String>,
    #[pyo3(get)]
    pub device_name: Option<String>,
}

#[pyclass]
pub struct DeviceMonitor {
    event_rx: Option<Mutex<Receiver<DeviceEvent>>>,
    thread_handle: Option<thread::JoinHandle<()>>,
    stop_tx: Option<Sender<()>>,
}

#[pymethods]
impl DeviceMonitor {
    fn poll(&self) -> PyResult<Vec<DeviceEvent>> {
        let mut events = Vec::new();
        if let Some(rx_mutex) = &self.event_rx {
            if let Ok(rx) = rx_mutex.lock() {
                while let Ok(event) = rx.try_recv() {
                    events.push(event);
                }
            }
        }
        Ok(events)
    }

    fn stop(&mut self) -> PyResult<()> {
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(());
        }
        if let Some(handle) = self.thread_handle.take() {
             Python::with_gil(|py| {
                py.allow_threads(|| {
                    let _ = handle.join();
                });
            });
        }
        Ok(())
    }
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
    #[pyo3(get)]
    pub bluetooth_profile: Option<String>,
}

#[pymethods]
impl Device {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        id: String,
        name: String,
        device_type: DeviceType,
        is_bluetooth: bool,
        sample_rate: u32,
        channels: u8,
        is_default: bool,
        bluetooth_profile: Option<String>,
    ) -> Self {
        Device {
            id,
            name,
            device_type,
            is_bluetooth,
            sample_rate,
            channels,
            is_default,
            bluetooth_profile,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Device(id='{}', name='{}', type={:?}, bt={})",
            self.id, self.name, self.device_type, self.is_bluetooth
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
                bluetooth_profile: None,
            },
            Device {
                id: "mock_speaker_1".to_string(),
                name: "Mock Speakers".to_string(),
                device_type: DeviceType::Speaker,
                is_bluetooth: false,
                sample_rate: 48000,
                channels: 2,
                is_default: true,
                bluetooth_profile: None,
            },
            Device {
                id: "mock_bt_headset".to_string(),
                name: "Mock Bluetooth Headset".to_string(),
                device_type: DeviceType::Microphone,
                is_bluetooth: true,
                sample_rate: 16000,
                channels: 1,
                is_default: false,
                bluetooth_profile: Some("headset-head-unit".to_string()),
            },
        ])
    }
}

#[pyfunction]
fn subscribe_device_changes() -> PyResult<DeviceMonitor> {
    #[cfg(feature = "real-audio")]
    {
        start_monitoring()
    }
    #[cfg(not(feature = "real-audio"))]
    {
        // Mock implementation
        use std::sync::mpsc::channel;
        use std::sync::{Arc, Mutex};
        let (event_tx, event_rx) = channel();
        // Send a fake event
        let _ = event_tx.send(DeviceEvent {
            type_: "added".to_string(),
            device_id: Some("mock_hotplug_mic".to_string()),
            device_name: Some("Mock Hotplug Microphone".to_string()),
        });
        
        Ok(DeviceMonitor {
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: None,
            stop_tx: None,
        })
    }
}

#[pyfunction]
fn start_recording(config: RecordingConfig) -> PyResult<RecordingSession> {
    start_recording_impl(config)
}

/// A Python module implemented in Rust.
#[pymodule]
fn quinoa_audio(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Device>()?;
    m.add_class::<DeviceType>()?;
    m.add_class::<RecordingConfig>()?;
    m.add_class::<RecordingSession>()?;
    m.add_class::<AudioEvent>()?;
    m.add_class::<DeviceMonitor>()?;
    m.add_class::<DeviceEvent>()?;
    m.add_function(wrap_pyfunction!(list_devices, m)?)?;
    m.add_function(wrap_pyfunction!(start_recording, m)?)?;
    m.add_function(wrap_pyfunction!(subscribe_device_changes, m)?)?;
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
            None,
        );

        assert_eq!(device.id, "test_id");
        assert_eq!(device.name, "Test Device");
        assert_eq!(device.device_type, DeviceType::Microphone);
        assert!(device.is_bluetooth);
        assert_eq!(device.sample_rate, 48000);
        assert_eq!(device.channels, 2);
        assert!(!device.is_default);
        assert!(device.bluetooth_profile.is_none());
    }
}
