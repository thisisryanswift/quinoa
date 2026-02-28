#[cfg(feature = "real-audio")]
use crate::{Device, DeviceType};
#[cfg(feature = "real-audio")]
use pipewire as pw;
#[cfg(feature = "real-audio")]
use pipewire::context::Context;
#[cfg(feature = "real-audio")]
use pipewire::main_loop::MainLoop;
#[cfg(feature = "real-audio")]
use serde::Deserialize;
#[cfg(feature = "real-audio")]
use std::sync::{Arc, Mutex};

/// Helper struct for parsing PipeWire default device JSON
#[cfg(feature = "real-audio")]
#[derive(Deserialize)]
struct DefaultDevice {
    name: String,
}

/// Parse a PipeWire default device value, which may be JSON or a plain string
#[cfg(feature = "real-audio")]
fn parse_default_device(json_val: &str) -> Option<String> {
    if json_val.starts_with('{') {
        serde_json::from_str::<DefaultDevice>(json_val)
            .ok()
            .map(|d| d.name)
    } else {
        Some(json_val.to_string())
    }
}

#[cfg(feature = "real-audio")]
pub fn list_devices_pw() -> Result<Vec<Device>, String> {
    pw::init();

    let mainloop =
        MainLoop::new(None).map_err(|e| format!("Failed to create main loop: {:?}", e))?;
    let context =
        Context::new(&mainloop).map_err(|e| format!("Failed to create context: {:?}", e))?;
    let core = context
        .connect(None)
        .map_err(|e| format!("Failed to connect to core: {:?}", e))?;
    let registry = core
        .get_registry()
        .map_err(|e| format!("Failed to get registry: {:?}", e))?;
    // Get a second registry proxy to use inside the listener to avoid borrow conflicts
    let registry_binding = core
        .get_registry()
        .map_err(|e| format!("Failed to get registry binding: {:?}", e))?;

    let devices = Arc::new(Mutex::new(Vec::new()));
    let devices_clone = devices.clone();

    let default_source = Arc::new(Mutex::new(None::<String>));
    let default_sink = Arc::new(Mutex::new(None::<String>));

    let default_source_clone = default_source.clone();
    let default_sink_clone = default_sink.clone();

    // We need to hold the metadata listener alive
    let metadata_listener_holder = Arc::new(Mutex::new(None));
    let metadata_listener_holder_clone = metadata_listener_holder.clone();

    // Listener for registry events
    let _listener = registry
        .add_listener_local()
        .global(move |global| {
            if let Some(props) = global.props {
                // Check for Metadata interface to find defaults
                if global.type_ == pipewire::types::ObjectType::Metadata
                    && props.get("metadata.name") == Some("default")
                {
                    if let Ok(metadata) =
                        registry_binding.bind::<pipewire::metadata::Metadata, _>(&global)
                    {
                        let default_source_clone = default_source_clone.clone();
                        let default_sink_clone = default_sink_clone.clone();

                        let listener = metadata
                            .add_listener_local()
                            .property(move |subject, key, _type, value| {
                                if subject == 0 {
                                    // Global settings
                                    if key == Some("default.audio.source") {
                                        if let Some(json_val) = value {
                                            if let Some(name) = parse_default_device(json_val) {
                                                if let Ok(mut guard) = default_source_clone.lock() {
                                                    *guard = Some(name);
                                                }
                                            }
                                        }
                                    } else if key == Some("default.audio.sink") {
                                        if let Some(json_val) = value {
                                            if let Some(name) = parse_default_device(json_val) {
                                                if let Ok(mut guard) = default_sink_clone.lock() {
                                                    *guard = Some(name);
                                                }
                                            }
                                        }
                                    }
                                }
                                0
                            })
                            .register();

                        if let Ok(mut guard) = metadata_listener_holder_clone.lock() {
                            *guard = Some((metadata, listener));
                        }
                    }
                }

                // Check for media.class to identify sources and sinks
                if let Some(media_class) = props.get("media.class") {
                    let device_type = if media_class == "Audio/Source" {
                        Some(DeviceType::Microphone)
                    } else if media_class == "Audio/Sink" {
                        Some(DeviceType::Speaker)
                    } else {
                        None
                    };

                    if let Some(dt) = device_type {
                        let name = props
                            .get("node.description")
                            .or_else(|| props.get("node.nick"))
                            .or_else(|| props.get("node.name"))
                            .unwrap_or("Unknown Device");

                        // Use the node name as the stable ID if possible, otherwise fallback to global ID
                        let id = props
                            .get("node.name")
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| global.id.to_string());

                        // Check for bluetooth
                        let is_bluetooth = props
                            .get("device.api")
                            .map(|v| v == "bluez5")
                            .unwrap_or(false);

                        // Get bluetooth profile if available
                        let bluetooth_profile =
                            props.get("api.bluez5.profile").map(|s| s.to_string());

                        // Default values for now - getting actual format requires more queries
                        let sample_rate = 48000;
                        let channels = 2;

                        let device = Device {
                            id,
                            name: name.to_string(),
                            device_type: dt,
                            is_bluetooth,
                            sample_rate,
                            channels,
                            is_default: false, // Will be updated after collection
                            bluetooth_profile,
                        };

                        if let Ok(mut guard) = devices_clone.lock() {
                            guard.push(device);
                        }
                    }
                }
            }
        })
        .register();

    // Perform a roundtrip to ensure we receive all initial globals
    let pending = core.sync(0).map_err(|e| format!("Sync failed: {:?}", e))?;
    let mainloop_clone = mainloop.clone();

    let _core_listener = core
        .add_listener_local()
        .done(move |id, seq| {
            if id == pipewire::core::PW_ID_CORE && seq == pending {
                mainloop_clone.quit();
            }
        })
        .register();

    mainloop.run();

    // Post-process to set is_default
    let mut result = devices.lock().expect("devices mutex poisoned").clone();
    let def_source = default_source
        .lock()
        .expect("default_source mutex poisoned")
        .clone();
    let def_sink = default_sink
        .lock()
        .expect("default_sink mutex poisoned")
        .clone();

    for device in &mut result {
        if device.device_type == DeviceType::Microphone {
            if let Some(ref def) = def_source {
                if &device.id == def {
                    device.is_default = true;
                }
            }
        } else if device.device_type == DeviceType::Speaker {
            if let Some(ref def) = def_sink {
                if &device.id == def {
                    device.is_default = true;
                }
            }
        }
    }

    Ok(result)
}
