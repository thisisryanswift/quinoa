#[cfg(feature = "real-audio")]
use pipewire as pw;
#[cfg(feature = "real-audio")]
use pipewire::main_loop::MainLoop;
#[cfg(feature = "real-audio")]
use pipewire::context::Context;
#[cfg(feature = "real-audio")]
use std::sync::{Arc, Mutex};
#[cfg(feature = "real-audio")]
use crate::{Device, DeviceType};

#[cfg(feature = "real-audio")]
pub fn list_devices_pw() -> Result<Vec<Device>, String> {
    pw::init();

    let mainloop = MainLoop::new(None).map_err(|e| format!("Failed to create main loop: {:?}", e))?;
    let context = Context::new(&mainloop).map_err(|e| format!("Failed to create context: {:?}", e))?;
    let core = context.connect(None).map_err(|e| format!("Failed to connect to core: {:?}", e))?;
    let registry = core.get_registry().map_err(|e| format!("Failed to get registry: {:?}", e))?;

    let devices = Arc::new(Mutex::new(Vec::new()));
    let devices_clone = devices.clone();

    // Listener for registry events
    let _listener = registry
        .add_listener_local()
        .global(move |global| {
            if let Some(props) = global.props {
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
                            is_default: false, // TODO: Implement default device detection via Metadata
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

    let result = devices.lock().unwrap().clone();
    Ok(result)
}
