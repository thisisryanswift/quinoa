use pyo3::prelude::*;
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread;

#[cfg(feature = "real-audio")]
use pipewire as pw;
#[cfg(feature = "real-audio")]
use pw::spa::param::format::{MediaSubtype, MediaType};
#[cfg(feature = "real-audio")]
use pw::spa::param::format_utils;
#[cfg(feature = "real-audio")]
use pw::spa::pod::Pod;
#[cfg(feature = "real-audio")]
use crate::capture::encoder::AudioEncoder;

#[derive(Clone, Debug)]
#[pyclass]
pub struct AudioEvent {
    #[pyo3(get)]
    pub type_: String,
    #[pyo3(get)]
    pub mic_level: Option<f32>,
    #[pyo3(get)]
    pub system_level: Option<f32>,
    #[pyo3(get)]
    pub message: Option<String>,
    #[pyo3(get)]
    pub device_id: Option<String>,
}

pub enum InternalAudioEvent {
    Started,
    Stopped,
    Error(String),
    Levels { mic: f32, system: f32 },
    DeviceLost(String),
    PipeWireDisconnected,
}

impl From<InternalAudioEvent> for AudioEvent {
    fn from(event: InternalAudioEvent) -> Self {
        match event {
            InternalAudioEvent::Started => AudioEvent {
                type_: "started".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: None,
            },
            InternalAudioEvent::Stopped => AudioEvent {
                type_: "stopped".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: None,
            },
            InternalAudioEvent::Error(msg) => AudioEvent {
                type_: "error".to_string(),
                mic_level: None,
                system_level: None,
                message: Some(msg),
                device_id: None,
            },
            InternalAudioEvent::Levels { mic, system } => AudioEvent {
                type_: "levels".to_string(),
                mic_level: Some(mic),
                system_level: Some(system),
                message: None,
                device_id: None,
            },
            InternalAudioEvent::DeviceLost(id) => AudioEvent {
                type_: "device_lost".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: Some(id),
            },
            InternalAudioEvent::PipeWireDisconnected => AudioEvent {
                type_: "pipewire_disconnected".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: None,
            },
        }
    }
}

#[derive(Clone, Debug)]
#[pyclass]
pub struct RecordingConfig {
    #[pyo3(get, set)]
    pub mic_device_id: Option<String>,
    #[pyo3(get, set)]
    pub system_audio: bool,
    #[pyo3(get, set)]
    pub output_dir: String,
    #[pyo3(get, set)]
    pub sample_rate: u32,
}

#[pymethods]
impl RecordingConfig {
    #[new]
    #[pyo3(signature = (output_dir, mic_device_id=None, system_audio=false, sample_rate=None))]
    fn new(
        output_dir: String,
        mic_device_id: Option<String>,
        system_audio: bool,
        sample_rate: Option<u32>,
    ) -> Self {
        RecordingConfig {
            mic_device_id,
            system_audio,
            output_dir,
            sample_rate: sample_rate.unwrap_or(48000),
        }
    }
}

enum AudioCommand {
    Stop,
}

#[pyclass]
pub struct RecordingSession {
    command_tx: Option<Sender<AudioCommand>>,
    event_rx: Option<Mutex<Receiver<InternalAudioEvent>>>,
    thread_handle: Option<thread::JoinHandle<()>>,
}

#[pymethods]
impl RecordingSession {
    fn stop(&mut self) -> PyResult<()> {
        if let Some(tx) = self.command_tx.take() {
            let _ = tx.send(AudioCommand::Stop);
        }
        
        if let Some(handle) = self.thread_handle.take() {
            // Release GIL to allow thread to join without deadlock if it calls back into Python
            Python::with_gil(|py| {
                py.allow_threads(|| {
                    let _ = handle.join();
                });
            });
        }
        Ok(())
    }

    fn poll_events(&self) -> PyResult<Vec<AudioEvent>> {
        let mut events = Vec::new();
        if let Some(rx_mutex) = &self.event_rx {
            if let Ok(rx) = rx_mutex.lock() {
                while let Ok(internal_event) = rx.try_recv() {
                    events.push(AudioEvent::from(internal_event));
                }
            }
        }
        Ok(events)
    }
}

pub fn start_recording_impl(config: RecordingConfig) -> PyResult<RecordingSession> {
    let (command_tx, command_rx) = channel();
    let (event_tx, event_rx) = channel();
    
    let config_clone = config.clone();
    
    let handle = thread::spawn(move || {
        #[cfg(feature = "real-audio")]
        {
            if let Err(e) = run_audio_thread(config_clone, command_rx, event_tx.clone()) {
                eprintln!("Audio thread error: {}", e);
                let _ = event_tx.send(InternalAudioEvent::Error(e));
            }
        }
        #[cfg(not(feature = "real-audio"))]
        {
            // Mock implementation: just wait for stop signal
            println!("Mock recording started for config: {:?}", config_clone);
            let _ = event_tx.send(InternalAudioEvent::Started);
            
            // Simulate some levels
            let _ = event_tx.send(InternalAudioEvent::Levels { mic: 0.5, system: 0.2 });
            
            let _ = command_rx.recv();
            println!("Mock recording stopped");
            let _ = event_tx.send(InternalAudioEvent::Stopped);
        }
    });

    Ok(RecordingSession {
        command_tx: Some(command_tx),
        event_rx: Some(Mutex::new(event_rx)),
        thread_handle: Some(handle),
    })
}

#[cfg(feature = "real-audio")]
struct SharedLevels {
    mic_level: Mutex<f32>,
    system_level: Mutex<f32>,
}

#[cfg(feature = "real-audio")]
struct StreamUserData {
    format: pw::spa::param::audio::AudioInfoRaw,
    encoder: Arc<Mutex<Option<AudioEncoder>>>,
    output_path: PathBuf,
    levels: Arc<SharedLevels>,
    is_mic: bool,
}

#[cfg(feature = "real-audio")]
impl Default for StreamUserData {
    fn default() -> Self {
        Self {
            format: Default::default(),
            encoder: Arc::new(Mutex::new(None)),
            output_path: PathBuf::new(),
            levels: Arc::new(SharedLevels {
                mic_level: Mutex::new(0.0),
                system_level: Mutex::new(0.0),
            }),
            is_mic: false,
        }
    }
}

#[cfg(feature = "real-audio")]
fn create_stream(
    core: &pw::core::Core,
    name: &str,
    properties: pw::properties::Properties,
    output_path: PathBuf,
    encoder: Arc<Mutex<Option<AudioEncoder>>>,
    levels: Arc<SharedLevels>,
    is_mic: bool,
) -> Result<(pw::stream::Stream, pw::stream::StreamListener<StreamUserData>), String> {
    use std::mem;

    let stream = pw::stream::Stream::new(core, name, properties)
        .map_err(|e| format!("Failed to create stream '{}': {:?}", name, e))?;

    let user_data = StreamUserData {
        format: Default::default(),
        encoder: encoder.clone(),
        output_path,
        levels,
        is_mic,
    };

    let listener = stream
        .add_local_listener_with_user_data(user_data)
        .param_changed(|_, user_data, id, param| {
            // NULL means to clear the format
            let Some(param) = param else {
                return;
            };
            if id != pw::spa::param::ParamType::Format.as_raw() {
                return;
            }

            let (media_type, media_subtype) = match format_utils::parse_format(param) {
                Ok(v) => v,
                Err(_) => return,
            };

            // only accept raw audio
            if media_type != MediaType::Audio || media_subtype != MediaSubtype::Raw {
                return;
            }

            // Parse the format
            if let Err(e) = user_data.format.parse(param) {
                eprintln!("Failed to parse audio format: {:?}", e);
                return;
            }

            let rate = user_data.format.rate();
            let channels = user_data.format.channels();
            println!("Negotiated format: {} Hz, {} channels", rate, channels);

            // Initialize encoder
            if let Ok(mut guard) = user_data.encoder.lock() {
                if guard.is_none() {
                    match AudioEncoder::new(&user_data.output_path, rate, channels as u16) {
                        Ok(encoder) => *guard = Some(encoder),
                        Err(e) => eprintln!("Failed to create encoder: {}", e),
                    }
                }
            }
        })
        .process(|stream, user_data| {
            let Some(mut buffer) = stream.dequeue_buffer() else {
                return;
            };

            let datas = buffer.datas_mut();
            if datas.is_empty() {
                return;
            }

            let data = &mut datas[0];
            let n_samples = data.chunk().size() / (mem::size_of::<f32>() as u32);

            if let Some(samples) = data.data() {
                // Convert bytes to f32 samples
                let float_samples: Vec<f32> = (0..n_samples as usize)
                    .map(|n| {
                        let start = n * mem::size_of::<f32>();
                        let end = start + mem::size_of::<f32>();
                        let bytes = &samples[start..end];
                        f32::from_le_bytes(bytes.try_into().unwrap())
                    })
                    .collect();

                // Calculate peak level
                let peak = float_samples.iter().map(|s| s.abs()).fold(0.0, f32::max);
                
                // Update shared levels
                if user_data.is_mic {
                    if let Ok(mut level) = user_data.levels.mic_level.lock() {
                        *level = f32::max(*level, peak);
                    }
                } else {
                    if let Ok(mut level) = user_data.levels.system_level.lock() {
                        *level = f32::max(*level, peak);
                    }
                }

                if let Ok(guard) = user_data.encoder.lock() {
                    if let Some(encoder) = guard.as_ref() {
                        let _ = encoder.write(&float_samples);
                    }
                }
            }
        })
        .register()
        .map_err(|e| format!("Failed to register listener: {:?}", e))?;

    // Create audio format params - request F32LE format
    let mut audio_info = pw::spa::param::audio::AudioInfoRaw::new();
    audio_info.set_format(pw::spa::param::audio::AudioFormat::F32LE);
    let obj = pw::spa::pod::Object {
        type_: pw::spa::utils::SpaTypes::ObjectParamFormat.as_raw(),
        id: pw::spa::param::ParamType::EnumFormat.as_raw(),
        properties: audio_info.into(),
    };
    let values: Vec<u8> = pw::spa::pod::serialize::PodSerializer::serialize(
        std::io::Cursor::new(Vec::new()),
        &pw::spa::pod::Value::Object(obj),
    )
    .map_err(|e| format!("Failed to serialize audio params: {:?}", e))?
    .0
    .into_inner();

    let mut params = [Pod::from_bytes(&values).unwrap()];

    // Connect stream
    stream
        .connect(
            pw::spa::utils::Direction::Input,
            None, // Let PipeWire choose the device, or use target.object property
            pw::stream::StreamFlags::AUTOCONNECT
                | pw::stream::StreamFlags::MAP_BUFFERS
                | pw::stream::StreamFlags::RT_PROCESS,
            &mut params,
        )
        .map_err(|e| format!("Failed to connect stream: {:?}", e))?;

    Ok((stream, listener))
}

#[cfg(feature = "real-audio")]
enum SessionError {
    Fatal(String),
    Recoverable(String),
}

#[cfg(feature = "real-audio")]
fn connect_and_run(
    config: &RecordingConfig,
    command_rx: Arc<Mutex<Receiver<AudioCommand>>>,
    event_tx: &Sender<InternalAudioEvent>,
) -> Result<(), SessionError> {
    pw::init();

    let mainloop = pw::main_loop::MainLoop::new(None)
        .map_err(|e| SessionError::Fatal(format!("Failed to create main loop: {:?}", e)))?;
    let context = pw::context::Context::new(&mainloop)
        .map_err(|e| SessionError::Fatal(format!("Failed to create context: {:?}", e)))?;
    
    // If connection fails, it might be recoverable (daemon restarting)
    let core = context.connect(None)
        .map_err(|e| SessionError::Recoverable(format!("Failed to connect to core: {:?}", e)))?;

    // Add listener for core events (disconnect)
    let _core_listener = core
        .add_listener_local()
        .error(|id, seq, res, message| {
            eprintln!("PipeWire error: id={}, seq={}, res={}, msg={}", id, seq, res, message);
        })
        .register();
        
    // We can't easily detect disconnect via the rust bindings' listener yet without more boilerplate,
    // but if the mainloop quits unexpectedly, we can treat it as a disconnect.

    let output_dir = PathBuf::from(&config.output_dir);
    if !output_dir.exists() {
        std::fs::create_dir_all(&output_dir)
            .map_err(|e| SessionError::Fatal(format!("Failed to create output dir: {:?}", e)))?;
    }

    // Shared levels state
    let levels = Arc::new(SharedLevels {
        mic_level: Mutex::new(0.0),
        system_level: Mutex::new(0.0),
    });

    // Notify started (or reconnected)
    let _ = event_tx.send(InternalAudioEvent::Started);

    // --- Microphone Stream ---
    let mic_encoder: Arc<Mutex<Option<AudioEncoder>>> = Arc::new(Mutex::new(None));
    let mic_encoder_finalize = mic_encoder.clone();

    let _mic_stream_handle = if let Some(ref mic_id) = config.mic_device_id {
        let props = pw::properties::properties! {
            *pw::keys::MEDIA_TYPE => "Audio",
            *pw::keys::MEDIA_CATEGORY => "Capture",
            *pw::keys::MEDIA_ROLE => "Communication",
            "target.object" => mic_id.as_str(),
        };
        let path = output_dir.join("microphone.wav");
        Some(create_stream(&core, "granola-mic", props, path, mic_encoder, levels.clone(), true)
            .map_err(|e| SessionError::Recoverable(format!("Failed to create mic stream: {}", e)))?)
    } else {
        None
    };

    // --- System Audio Stream ---
    let sys_encoder: Arc<Mutex<Option<AudioEncoder>>> = Arc::new(Mutex::new(None));
    let sys_encoder_finalize = sys_encoder.clone();

    let _sys_stream_handle = if config.system_audio {
        let props = pw::properties::properties! {
            *pw::keys::MEDIA_TYPE => "Audio",
            *pw::keys::MEDIA_CATEGORY => "Capture",
            *pw::keys::MEDIA_ROLE => "Music",
            *pw::keys::STREAM_CAPTURE_SINK => "true",
        };
        let path = output_dir.join("system.wav");
        Some(create_stream(&core, "granola-sys", props, path, sys_encoder, levels.clone(), false)
            .map_err(|e| SessionError::Recoverable(format!("Failed to create system stream: {}", e)))?)
    } else {
        None
    };

    // --- Watchdog / Command Check ---
    let loop_clone = mainloop.clone();
    let event_tx_clone = event_tx.clone();
    let levels_clone = levels.clone();
    let command_rx_clone = command_rx.clone();
    
    // We need to know if we quit because of a stop command or an error
    let stop_requested = Arc::new(Mutex::new(false));
    let stop_requested_clone = stop_requested.clone();

    let timer = mainloop.loop_().add_timer(move |_| {
        // Check commands
        if let Ok(rx) = command_rx_clone.lock() {
            if let Ok(cmd) = rx.try_recv() {
                match cmd {
                    AudioCommand::Stop => {
                        if let Ok(mut stop) = stop_requested_clone.lock() {
                            *stop = true;
                        }
                        loop_clone.quit();
                    }
                }
            }
        }
        
        // Send levels
        let mut mic_peak = 0.0;
        let mut sys_peak = 0.0;
        
        if let Ok(mut level) = levels_clone.mic_level.lock() {
            mic_peak = *level;
            *level = 0.0; // Reset for next window
        }
        if let Ok(mut level) = levels_clone.system_level.lock() {
            sys_peak = *level;
            *level = 0.0; // Reset for next window
        }
        
        let _ = event_tx_clone.send(InternalAudioEvent::Levels { 
            mic: mic_peak, 
            system: sys_peak 
        });
    });

    let timeout = std::time::Duration::from_millis(100);
    timer.update_timer(Some(timeout), Some(timeout));

    mainloop.run();

    // Finalize encoders
    if let Ok(guard) = mic_encoder_finalize.lock() {
        if let Some(encoder) = guard.as_ref() {
            let _ = encoder.finalize();
        }
    }
    if let Ok(guard) = sys_encoder_finalize.lock() {
        if let Some(encoder) = guard.as_ref() {
            let _ = encoder.finalize();
        }
    }

    // Check if we stopped intentionally
    if let Ok(stop) = stop_requested.lock() {
        if *stop {
            return Ok(());
        }
    }

    // If we get here and didn't request stop, it means the mainloop quit unexpectedly
    Err(SessionError::Recoverable("PipeWire mainloop exited unexpectedly".to_string()))
}

#[cfg(feature = "real-audio")]
fn run_audio_thread(
    config: RecordingConfig,
    command_rx: Receiver<AudioCommand>,
    event_tx: Sender<InternalAudioEvent>,
) -> Result<(), String> {
    let command_rx = Arc::new(Mutex::new(command_rx));
    
    loop {
        match connect_and_run(&config, command_rx.clone(), &event_tx) {
            Ok(()) => {
                // Clean stop
                let _ = event_tx.send(InternalAudioEvent::Stopped);
                return Ok(());
            }
            Err(SessionError::Fatal(e)) => {
                // Fatal error, give up
                let _ = event_tx.send(InternalAudioEvent::Error(e.clone()));
                return Err(e);
            }
            Err(SessionError::Recoverable(e)) => {
                // Recoverable, notify and retry
                eprintln!("Recoverable audio error: {}. Reconnecting...", e);
                let _ = event_tx.send(InternalAudioEvent::PipeWireDisconnected);
                
                // Wait before retrying
                thread::sleep(std::time::Duration::from_secs(2));
            }
        }
    }
}
