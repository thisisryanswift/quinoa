use pyo3::prelude::*;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Mutex;
use std::thread;

#[cfg(feature = "real-audio")]
use pipewire as pw;
#[cfg(feature = "real-audio")]
use pipewire::context::Context;
#[cfg(feature = "real-audio")]
use pipewire::main_loop::MainLoop;

use crate::{DeviceEvent, DeviceMonitor};

pub fn start_monitoring() -> PyResult<DeviceMonitor> {
    let (event_tx, event_rx) = channel();
    let (stop_tx, stop_rx) = channel();

    let handle = thread::spawn(move || {
        #[cfg(feature = "real-audio")]
        {
            if let Err(e) = run_monitor_thread(event_tx, stop_rx) {
                eprintln!("Device monitor thread error: {}", e);
            }
        }
        #[cfg(not(feature = "real-audio"))]
        {
            // Mock implementation
            let _ = stop_rx.recv();
        }
    });

    Ok(DeviceMonitor {
        event_rx: Some(Mutex::new(event_rx)),
        thread_handle: Some(handle),
        stop_tx: Some(stop_tx),
    })
}

#[cfg(feature = "real-audio")]
fn run_monitor_thread(event_tx: Sender<DeviceEvent>, stop_rx: Receiver<()>) -> Result<(), String> {
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

    let event_tx_clone = event_tx.clone();
    let event_tx_remove = event_tx.clone();

    // Listener for registry events
    let _listener = registry
        .add_listener_local()
        .global(move |global| {
            if let Some(props) = global.props {
                if let Some(media_class) = props.get("media.class") {
                    if media_class == "Audio/Source" || media_class == "Audio/Sink" {
                        let name = props
                            .get("node.description")
                            .or_else(|| props.get("node.nick"))
                            .or_else(|| props.get("node.name"))
                            .unwrap_or("Unknown Device");

                        let id = props
                            .get("node.name")
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| global.id.to_string());

                        let _ = event_tx_clone.send(DeviceEvent {
                            type_: "added".to_string(),
                            device_id: Some(id),
                            device_name: Some(name.to_string()),
                        });
                    }
                }
            }
        })
        .global_remove(move |id| {
            let _ = event_tx_remove.send(DeviceEvent {
                type_: "removed".to_string(),
                device_id: Some(id.to_string()),
                device_name: None,
            });
        })
        .register();

    // Watchdog/Stop check
    let loop_clone = mainloop.clone();
    let timer = mainloop.loop_().add_timer(move |_| {
        if let Ok(_) = stop_rx.try_recv() {
            loop_clone.quit();
        }
    });

    let timeout = std::time::Duration::from_millis(200);
    timer.update_timer(Some(timeout), Some(timeout));

    mainloop.run();
    Ok(())
}
