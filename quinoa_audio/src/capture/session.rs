use pyo3::prelude::*;
use std::sync::mpsc::{channel, Receiver as StdReceiver, Sender as StdSender};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

#[cfg(feature = "real-audio")]
use std::path::PathBuf;
#[cfg(feature = "real-audio")]
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicUsize, Ordering};
#[cfg(any(feature = "real-audio", test))]
use std::sync::Arc;
#[cfg(feature = "real-audio")]
use std::time::Instant;

#[cfg(feature = "real-audio")]
use crate::capture::encoder::AudioEncoder;
#[cfg(feature = "real-audio")]
use crossbeam_channel::{bounded, Sender as AudioSender, TrySendError};
#[cfg(feature = "real-audio")]
use crossbeam_queue::ArrayQueue;
#[cfg(feature = "real-audio")]
use pipewire as pw;
#[cfg(feature = "real-audio")]
use pw::spa::param::format::{MediaSubtype, MediaType};
#[cfg(feature = "real-audio")]
use pw::spa::param::format_utils;
#[cfg(feature = "real-audio")]
use pw::spa::pod::Pod;

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
    Paused,
    Resumed,
    Error(String),
    Levels {
        mic: f32,
        system: f32,
    },
    DeviceLost(String),
    PipeWireDisconnected,
    MicSwitched(String),
    MicSwitchFailed {
        requested: String,
        fallback: Option<String>,
    },
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
            InternalAudioEvent::Paused => AudioEvent {
                type_: "paused".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: None,
            },
            InternalAudioEvent::Resumed => AudioEvent {
                type_: "resumed".to_string(),
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
            InternalAudioEvent::MicSwitched(id) => AudioEvent {
                type_: "mic_switched".to_string(),
                mic_level: None,
                system_level: None,
                message: None,
                device_id: Some(id),
            },
            InternalAudioEvent::MicSwitchFailed {
                requested,
                fallback,
            } => AudioEvent {
                type_: "mic_switch_failed".to_string(),
                mic_level: None,
                system_level: None,
                message: Some(format!(
                    "Failed to switch to {}. Fallback: {:?}",
                    requested, fallback
                )),
                device_id: fallback,
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
    #[pyo3(get, set)]
    pub mic_channels: u16,
    #[pyo3(get, set)]
    pub system_channels: u16,
}

#[pymethods]
impl RecordingConfig {
    #[new]
    #[pyo3(signature = (output_dir, mic_device_id=None, system_audio=false, sample_rate=None, mic_channels=None, system_channels=None))]
    fn new(
        output_dir: String,
        mic_device_id: Option<String>,
        system_audio: bool,
        sample_rate: Option<u32>,
        mic_channels: Option<u16>,
        system_channels: Option<u16>,
    ) -> Self {
        RecordingConfig {
            mic_device_id,
            system_audio,
            output_dir,
            sample_rate: sample_rate.unwrap_or(48000),
            mic_channels: mic_channels.unwrap_or(1),
            system_channels: system_channels.unwrap_or(2),
        }
    }
}

enum AudioCommand {
    Stop,
    Pause,
    Resume,
    SwitchMic(String),
}

#[pyclass]
pub struct RecordingSession {
    command_tx: Option<StdSender<AudioCommand>>,
    event_rx: Option<Mutex<StdReceiver<InternalAudioEvent>>>,
    thread_handle: Option<thread::JoinHandle<Result<(), String>>>,
    pending_events: Vec<InternalAudioEvent>,
}

impl RecordingSession {
    /// Synchronous cleanup seam used by `stop` (which releases the GIL) and by tests.
    fn shutdown_sync(&mut self) -> Option<String> {
        if let Some(tx) = self.command_tx.take() {
            let _ = tx.send(AudioCommand::Stop);
        }

        let thread_result = self.thread_handle.take().map(|handle| handle.join());

        let mut event_error: Option<String> = None;
        if let Some(rx_mutex) = self.event_rx.take() {
            let rx = rx_mutex.into_inner().unwrap_or_else(|e| e.into_inner());
            while let Ok(event) = rx.try_recv() {
                if let InternalAudioEvent::Error(msg) = event {
                    // Keep only the first error to return from stop. Do not also
                    // surface it through poll_events so callers don't get the same
                    // error twice.
                    if event_error.is_none() {
                        event_error = Some(msg);
                    }
                } else {
                    // Preserve non-error terminal/events such as Stopped so they
                    // remain pollable after stop returns.
                    self.pending_events.push(event);
                }
            }
        }

        match thread_result {
            Some(Ok(Ok(()))) => event_error,
            Some(Ok(Err(e))) => Some(e),
            Some(Err(_)) => Some("audio thread panicked".to_string()),
            None => event_error,
        }
    }
}

#[pymethods]
impl RecordingSession {
    fn stop(&mut self, py: Python<'_>) -> PyResult<()> {
        // Release the GIL while joining the audio thread so Python is not blocked.
        let err = py.allow_threads(|| self.shutdown_sync());
        match err {
            Some(msg) => Err(pyo3::exceptions::PyRuntimeError::new_err(msg)),
            None => Ok(()),
        }
    }

    fn pause(&self) -> PyResult<()> {
        if let Some(tx) = &self.command_tx {
            tx.send(AudioCommand::Pause).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to send pause command: {}",
                    e
                ))
            })?;
        }
        Ok(())
    }

    fn resume(&self) -> PyResult<()> {
        if let Some(tx) = &self.command_tx {
            tx.send(AudioCommand::Resume).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to send resume command: {}",
                    e
                ))
            })?;
        }
        Ok(())
    }

    fn poll_events(&mut self) -> PyResult<Vec<AudioEvent>> {
        let mut events: Vec<AudioEvent> = self
            .pending_events
            .drain(..)
            .map(AudioEvent::from)
            .collect();
        if let Some(rx_mutex) = &self.event_rx {
            if let Ok(rx) = rx_mutex.lock() {
                while let Ok(internal_event) = rx.try_recv() {
                    events.push(AudioEvent::from(internal_event));
                }
            }
        }
        Ok(events)
    }

    fn switch_mic(&self, new_device_id: String) -> PyResult<()> {
        if let Some(tx) = &self.command_tx {
            tx.send(AudioCommand::SwitchMic(new_device_id))
                .map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "Failed to send switch_mic command: {}",
                        e
                    ))
                })?;
        }
        Ok(())
    }
}

impl Drop for RecordingSession {
    fn drop(&mut self) {
        // Do not synchronously join while Python may hold the GIL. Move the
        // remaining resources into a short-lived finalizer thread that sends the
        // stop signal and joins the audio thread. The recording is never
        // detached without a stop signal.
        let command_tx = self.command_tx.take();
        let thread_handle = self.thread_handle.take();
        let event_rx = self.event_rx.take();
        if command_tx.is_some() || thread_handle.is_some() {
            std::thread::spawn(move || {
                if let Some(tx) = command_tx {
                    let _ = tx.send(AudioCommand::Stop);
                }
                if let Some(handle) = thread_handle {
                    let _ = handle.join();
                }
                drop(event_rx);
            });
        }
    }
}

pub fn start_recording_impl(config: RecordingConfig) -> PyResult<RecordingSession> {
    let (command_tx, command_rx) = channel();
    let (event_tx, event_rx) = channel();

    let config_clone = config.clone();

    let handle = thread::spawn(move || {
        #[cfg(feature = "real-audio")]
        {
            match run_audio_thread(config_clone, command_rx, event_tx.clone()) {
                Ok(()) => {
                    let _ = event_tx.send(InternalAudioEvent::Stopped);
                    Ok(())
                }
                Err(e) => {
                    let _ = event_tx.send(InternalAudioEvent::Error(e.clone()));
                    Err(e)
                }
            }
        }
        #[cfg(not(feature = "real-audio"))]
        {
            // Mock implementation: just wait for stop signal
            println!("Mock recording started for config: {:?}", config_clone);
            let _ = event_tx.send(InternalAudioEvent::Started);

            let mut is_paused = false;
            let mut current_mic = config_clone.mic_device_id.clone();
            let result = loop {
                // Simulate some levels (only when not paused)
                if !is_paused {
                    let _ = event_tx.send(InternalAudioEvent::Levels {
                        mic: 0.5,
                        system: 0.2,
                    });
                } else {
                    let _ = event_tx.send(InternalAudioEvent::Levels {
                        mic: 0.0,
                        system: 0.0,
                    });
                }

                // Check for commands
                match command_rx.recv_timeout(Duration::from_millis(100)) {
                    Ok(AudioCommand::Stop) => {
                        println!("Mock recording stopped");
                        let _ = event_tx.send(InternalAudioEvent::Stopped);
                        break Ok(());
                    }
                    Ok(AudioCommand::Pause) => {
                        println!("Mock recording paused");
                        is_paused = true;
                        let _ = event_tx.send(InternalAudioEvent::Paused);
                    }
                    Ok(AudioCommand::Resume) => {
                        println!("Mock recording resumed");
                        is_paused = false;
                        let _ = event_tx.send(InternalAudioEvent::Resumed);
                    }
                    Ok(AudioCommand::SwitchMic(new_id)) => {
                        println!("Mock: switching mic from {:?} to {}", current_mic, new_id);
                        current_mic = Some(new_id.clone());
                        let _ = event_tx.send(InternalAudioEvent::MicSwitched(new_id));
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                        // Timeout, continue loop
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                        break Ok(());
                    }
                }
            };
            result
        }
    });

    Ok(RecordingSession {
        command_tx: Some(command_tx),
        event_rx: Some(Mutex::new(event_rx)),
        thread_handle: Some(handle),
        pending_events: Vec::new(),
    })
}

#[cfg(feature = "real-audio")]
struct StreamCounters {
    corrupted: AtomicUsize,
    unmapped: AtomicUsize,
    misaligned: AtomicUsize,
    dropped: AtomicUsize,
    switch_gaps: AtomicUsize,
}

#[cfg(feature = "real-audio")]
#[derive(Debug)]
struct StreamCountersSnapshot {
    corrupted: usize,
    unmapped: usize,
    misaligned: usize,
    dropped: usize,
    switch_gaps: usize,
}

#[cfg(feature = "real-audio")]
impl StreamCountersSnapshot {
    fn has_loss(&self) -> bool {
        self.corrupted > 0
            || self.unmapped > 0
            || self.misaligned > 0
            || self.dropped > 0
            || self.switch_gaps > 0
    }
}

#[cfg(feature = "real-audio")]
impl StreamCounters {
    fn new() -> Self {
        Self {
            corrupted: AtomicUsize::new(0),
            unmapped: AtomicUsize::new(0),
            misaligned: AtomicUsize::new(0),
            dropped: AtomicUsize::new(0),
            switch_gaps: AtomicUsize::new(0),
        }
    }

    fn record_corrupted(&self, n: usize) {
        self.corrupted.fetch_add(n, Ordering::Release);
    }

    fn record_unmapped(&self, n: usize) {
        self.unmapped.fetch_add(n, Ordering::Release);
    }

    fn record_misaligned(&self, n: usize) {
        self.misaligned.fetch_add(n, Ordering::Release);
    }

    fn record_dropped(&self, n: usize) {
        self.dropped.fetch_add(n, Ordering::Release);
    }

    fn record_switch_gap(&self, n: usize) {
        self.switch_gaps.fetch_add(n, Ordering::Release);
    }

    fn take_delta(&self) -> StreamCountersSnapshot {
        StreamCountersSnapshot {
            corrupted: self.corrupted.swap(0, Ordering::Acquire),
            unmapped: self.unmapped.swap(0, Ordering::Acquire),
            misaligned: self.misaligned.swap(0, Ordering::Acquire),
            dropped: self.dropped.swap(0, Ordering::Acquire),
            switch_gaps: self.switch_gaps.swap(0, Ordering::Acquire),
        }
    }
}

#[cfg(feature = "real-audio")]
struct SharedLevels {
    mic_level: AtomicU32,
    system_level: AtomicU32,
    mic: StreamCounters,
    sys: StreamCounters,
}

#[cfg(feature = "real-audio")]
impl SharedLevels {
    fn counters(&self, is_mic: bool) -> &StreamCounters {
        if is_mic {
            &self.mic
        } else {
            &self.sys
        }
    }
}

#[cfg(feature = "real-audio")]
enum EncoderMessage {
    Init {
        sample_rate: u32,
        channels: u16,
        format_accepted: Arc<AtomicBool>,
    },
    Write(Vec<i16>),
}

#[cfg(feature = "real-audio")]
struct EncoderWorkerHandle {
    tx: AudioSender<EncoderMessage>,
    pool: Arc<ArrayQueue<Vec<i16>>>,
    failed: Arc<AtomicBool>,
    error_message: Arc<Mutex<Option<String>>>,
}

#[cfg(feature = "real-audio")]
impl Clone for EncoderWorkerHandle {
    fn clone(&self) -> Self {
        Self {
            tx: self.tx.clone(),
            pool: self.pool.clone(),
            failed: self.failed.clone(),
            error_message: self.error_message.clone(),
        }
    }
}

#[cfg(feature = "real-audio")]
struct EncoderWorker {
    tx: AudioSender<EncoderMessage>,
    pool: Arc<ArrayQueue<Vec<i16>>>,
    failed: Arc<AtomicBool>,
    error_message: Arc<Mutex<Option<String>>>,
    handle: thread::JoinHandle<()>,
}

#[cfg(feature = "real-audio")]
impl EncoderWorker {
    const POOL_SIZE: usize = 8;
    // Large enough for typical PipeWire buffers (64 KB / 4 bytes per F32LE sample).
    const MAX_SAMPLES: usize = 65536;

    fn new(output_path: PathBuf) -> Self {
        let (tx, rx) = bounded::<EncoderMessage>(Self::POOL_SIZE);
        let pool: Arc<ArrayQueue<Vec<i16>>> = Arc::new(ArrayQueue::new(Self::POOL_SIZE));
        for _ in 0..Self::POOL_SIZE {
            let _ = pool.push(Vec::with_capacity(Self::MAX_SAMPLES));
        }
        let pool_for_thread = pool.clone();
        let current_format: Arc<Mutex<Option<(u32, u16)>>> = Arc::new(Mutex::new(None));
        let current_format_for_thread = current_format.clone();
        let failed: Arc<AtomicBool> = Arc::new(AtomicBool::new(false));
        let failed_for_thread = failed.clone();
        let error_message: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
        let error_message_for_thread = error_message.clone();

        let handle = thread::spawn(move || {
            let mut encoder: Option<AudioEncoder> = None;
            let mut result: Result<(), String> = Ok(());
            while let Ok(msg) = rx.recv() {
                match msg {
                    EncoderMessage::Init {
                        sample_rate,
                        channels,
                        format_accepted,
                    } => {
                        // The format_accepted flag is only set to true after the
                        // worker has actually accepted (and, if needed, created)
                        // the encoder for this format. This prevents events such
                        // as MicSwitched from being emitted when an Init message
                        // is merely queued.
                        match current_format_for_thread.lock() {
                            Ok(mut fmt) => {
                                if let Some((old_rate, old_ch)) = *fmt {
                                    if old_rate != sample_rate || old_ch != channels {
                                        result = Err(format!(
                                            "Audio format changed from {} Hz/{} ch to {} Hz/{} ch; cannot append to same WAV",
                                            old_rate, old_ch, sample_rate, channels
                                        ));
                                        break;
                                    }
                                }
                                *fmt = Some((sample_rate, channels));
                            }
                            Err(_) => {
                                result = Err("encoder format mutex poisoned".to_string());
                                break;
                            }
                        }
                        if encoder.is_none() {
                            match AudioEncoder::new(&output_path, sample_rate, channels) {
                                Ok(enc) => encoder = Some(enc),
                                Err(e) => {
                                    result = Err(format!("Encoder init failed: {}", e));
                                    break;
                                }
                            }
                        }
                        format_accepted.store(true, Ordering::Release);
                    }
                    EncoderMessage::Write(mut samples) => {
                        if let Some(enc) = encoder.as_ref() {
                            if let Err(e) = enc.write_i16(&samples) {
                                result = Err(format!("Encoder write failed: {}", e));
                                break;
                            }
                        }
                        samples.clear();
                        let _ = pool_for_thread.push(samples);
                    }
                }
            }
            if let Some(enc) = encoder {
                if let Err(e) = enc.finalize() {
                    if result.is_ok() {
                        result = Err(format!("Encoder finalize failed: {}", e));
                    }
                }
            }
            if let Err(e) = result {
                failed_for_thread.store(true, Ordering::Release);
                if let Ok(mut msg) = error_message_for_thread.lock() {
                    *msg = Some(e);
                }
            }
        });

        Self {
            tx,
            pool,
            failed,
            error_message,
            handle,
        }
    }

    fn handle(&self) -> EncoderWorkerHandle {
        EncoderWorkerHandle {
            tx: self.tx.clone(),
            pool: self.pool.clone(),
            failed: self.failed.clone(),
            error_message: self.error_message.clone(),
        }
    }

    fn finalize(self) -> Result<(), String> {
        // Drop the sender so the worker's recv returns and it can finalize the WAV file.
        drop(self.tx);
        let join_result = self.handle.join();
        let worker_error = self.error_message.lock().ok().and_then(|m| m.clone());
        match (join_result, worker_error) {
            (Ok(()), None) => Ok(()),
            (Ok(()), Some(msg)) => Err(msg),
            (Err(e), err) => {
                let panic_msg = if let Some(s) = e.downcast_ref::<String>() {
                    s.clone()
                } else if let Some(s) = e.downcast_ref::<&str>() {
                    (*s).to_string()
                } else {
                    "encoder thread panicked".to_string()
                };
                Err(err.unwrap_or(panic_msg))
            }
        }
    }
}

#[cfg(feature = "real-audio")]
struct StreamUserData {
    format: pw::spa::param::audio::AudioInfoRaw,
    encoder_tx: Option<AudioSender<EncoderMessage>>,
    encoder_initialized: AtomicBool,
    negotiated: Arc<AtomicU64>,
    active: Arc<AtomicBool>,
    ready: Arc<AtomicBool>,
    format_error: Arc<AtomicBool>,
    format_accepted: Arc<AtomicBool>,
    expected_format: (u32, u16),
    buffer_pool: Arc<ArrayQueue<Vec<i16>>>,
    failed: Arc<AtomicBool>,
    levels: Arc<SharedLevels>,
    is_mic: bool,
    is_paused: Arc<AtomicBool>,
}

#[cfg(feature = "real-audio")]
impl Default for StreamUserData {
    fn default() -> Self {
        Self {
            format: Default::default(),
            encoder_tx: None,
            encoder_initialized: AtomicBool::new(false),
            negotiated: Arc::new(AtomicU64::new(0)),
            active: Arc::new(AtomicBool::new(false)),
            ready: Arc::new(AtomicBool::new(false)),
            format_error: Arc::new(AtomicBool::new(false)),
            format_accepted: Arc::new(AtomicBool::new(false)),
            expected_format: (0, 0),
            buffer_pool: Arc::new(ArrayQueue::new(EncoderWorker::POOL_SIZE)),
            failed: Arc::new(AtomicBool::new(false)),
            levels: Arc::new(SharedLevels {
                mic_level: AtomicU32::new(0),
                system_level: AtomicU32::new(0),
                mic: StreamCounters::new(),
                sys: StreamCounters::new(),
            }),
            is_mic: false,
            is_paused: Arc::new(AtomicBool::new(false)),
        }
    }
}

#[cfg(feature = "real-audio")]
fn pack_format(rate: u32, channels: u16) -> u64 {
    ((rate as u64) << 16) | (channels as u64)
}

#[cfg(feature = "real-audio")]
fn unpack_format(packed: u64) -> (u32, u16) {
    let rate = (packed >> 16) as u32;
    let channels = (packed & 0xFFFF) as u16;
    (rate, channels)
}

#[cfg(feature = "real-audio")]
#[allow(dead_code)]
struct AudioStream {
    stream: pw::stream::StreamRc,
    listener: pw::stream::StreamListener<StreamUserData>,
    active: Arc<AtomicBool>,
    ready: Arc<AtomicBool>,
    negotiated: Arc<AtomicU64>,
    format_error: Arc<AtomicBool>,
    format_accepted: Arc<AtomicBool>,
}

#[cfg(feature = "real-audio")]
fn create_stream(
    core: pw::core::CoreRc,
    name: &str,
    properties: pw::properties::PropertiesBox,
    worker: &EncoderWorkerHandle,
    levels: Arc<SharedLevels>,
    is_mic: bool,
    is_paused: Arc<AtomicBool>,
    expected_format: (u32, u16),
) -> Result<AudioStream, String> {
    use std::mem;

    let stream = pw::stream::StreamRc::new(core, name, properties)
        .map_err(|e| format!("Failed to create stream '{}': {:?}", name, e))?;

    let active = Arc::new(AtomicBool::new(false));
    let ready = Arc::new(AtomicBool::new(false));
    let negotiated = Arc::new(AtomicU64::new(0));
    let format_error = Arc::new(AtomicBool::new(false));
    let format_accepted = Arc::new(AtomicBool::new(false));

    let user_data = StreamUserData {
        format: Default::default(),
        encoder_tx: Some(worker.tx.clone()),
        encoder_initialized: AtomicBool::new(false),
        negotiated: negotiated.clone(),
        active: active.clone(),
        ready: ready.clone(),
        format_error: format_error.clone(),
        format_accepted: format_accepted.clone(),
        expected_format,
        buffer_pool: worker.pool.clone(),
        failed: worker.failed.clone(),
        levels,
        is_mic,
        is_paused,
    };

    let listener = stream
        .add_local_listener_with_user_data(user_data)
        .param_changed(|_, user_data, id, param| {
            // NULL means to clear the format.
            let Some(param) = param else {
                user_data.negotiated.store(0, Ordering::Release);
                user_data
                    .encoder_initialized
                    .store(false, Ordering::Release);
                return;
            };
            if id != pw::spa::param::ParamType::Format.as_raw() {
                return;
            }

            let (media_type, media_subtype) = match format_utils::parse_format(param) {
                Ok(v) => v,
                Err(_) => {
                    user_data.format_error.store(true, Ordering::Release);
                    user_data.negotiated.store(0, Ordering::Release);
                    return;
                }
            };

            // only accept raw audio
            if media_type != MediaType::Audio || media_subtype != MediaSubtype::Raw {
                user_data.format_error.store(true, Ordering::Release);
                user_data.negotiated.store(0, Ordering::Release);
                return;
            }

            // Parse the format
            if let Err(_) = user_data.format.parse(param) {
                user_data.format_error.store(true, Ordering::Release);
                user_data.negotiated.store(0, Ordering::Release);
                return;
            }

            // Only accept the float format we requested; other sample sizes would
            // break the byte-to-f32 conversion in the process callback.
            if user_data.format.format() != pw::spa::param::audio::AudioFormat::F32LE {
                user_data.format_error.store(true, Ordering::Release);
                user_data.negotiated.store(0, Ordering::Release);
                return;
            }

            let rate = user_data.format.rate();
            let channels = user_data.format.channels();

            // Constrain to the stable configured format. If the device negotiates
            // something different, do not continue parsing bytes under stale
            // assumptions.
            if rate != user_data.expected_format.0 || channels != user_data.expected_format.1 as u32
            {
                user_data.format_error.store(true, Ordering::Release);
                user_data.negotiated.store(0, Ordering::Release);
                return;
            }

            // Record the negotiated format. Activation and writing are gated by
            // the main-loop timer so that mic switching can keep the old stream
            // live until the replacement is accepted.
            user_data.format_error.store(false, Ordering::Release);
            user_data
                .negotiated
                .store(pack_format(rate, channels as u16), Ordering::Release);
            user_data
                .encoder_initialized
                .store(false, Ordering::Release);
        })
        .process(|stream, user_data| {
            let Some(mut buffer) = stream.dequeue_buffer() else {
                return;
            };

            let datas = buffer.datas_mut();
            if datas.is_empty() {
                return;
            }

            // Gated by the main-loop timer so that mic switching can hold the
            // old stream live until the replacement is accepted.
            if user_data.failed.load(Ordering::Acquire)
                || user_data.format_error.load(Ordering::Acquire)
                || !user_data.active.load(Ordering::Acquire)
            {
                return;
            }

            let counters = user_data.levels.counters(user_data.is_mic);
            let data = &mut datas[0];

            // Read chunk metadata before borrowing the payload so we don't hold
            // an immutable borrow while calling data.data().
            let (corrupted, offset, size) = {
                let chunk = data.chunk();
                (
                    chunk
                        .flags()
                        .contains(pw::spa::buffer::ChunkFlags::CORRUPTED),
                    chunk.offset() as usize,
                    chunk.size() as usize,
                )
            };
            if corrupted {
                counters.record_corrupted(1);
                return;
            }

            let Some(samples_bytes) = data
                .data()
                .and_then(|bytes| bytes.get(offset..offset.saturating_add(size)))
            else {
                counters.record_unmapped(1);
                return;
            };
            let total = samples_bytes.len();
            if total == 0 {
                return;
            }
            if total % mem::size_of::<f32>() != 0 {
                counters.record_misaligned(1);
                return;
            }
            let n_samples = total / mem::size_of::<f32>();

            // Try to initialize the encoder from the format negotiated in
            // param_changed. Retry on a full queue; do not count an Init retry
            // as a payload drop.
            if !user_data.encoder_initialized.load(Ordering::Acquire) {
                let packed = user_data.negotiated.load(Ordering::Acquire);
                if packed == 0 {
                    return;
                }
                let (rate, channels) = unpack_format(packed);
                if let Some(ref tx) = user_data.encoder_tx {
                    match tx.try_send(EncoderMessage::Init {
                        sample_rate: rate,
                        channels,
                        format_accepted: user_data.format_accepted.clone(),
                    }) {
                        Ok(()) => {
                            user_data.encoder_initialized.store(true, Ordering::Release);
                        }
                        Err(TrySendError::Full(_)) => {
                            return;
                        }
                        Err(TrySendError::Disconnected(_)) => {
                            user_data.failed.store(true, Ordering::Release);
                            return;
                        }
                    }
                } else {
                    return;
                }
            }

            // If this stream is not yet marked ready (e.g. a pending mic switch
            // whose encoder has not been accepted), return before touching the
            // shared buffer pool so the live old stream is not starved and no
            // false drop is recorded.
            if !user_data.ready.load(Ordering::Acquire) {
                return;
            }

            // Reuse a pre-allocated buffer. If the pool is empty or the chunk is
            // larger than expected, treat it as a payload drop.
            let mut local_buffer = match user_data.buffer_pool.pop() {
                Some(b) => b,
                None => {
                    counters.record_dropped(1);
                    return;
                }
            };
            if n_samples > local_buffer.capacity() {
                let _ = user_data.buffer_pool.push(local_buffer);
                counters.record_dropped(1);
                return;
            }
            local_buffer.clear();

            let mut peak = 0.0f32;
            for chunk in samples_bytes.chunks_exact(mem::size_of::<f32>()) {
                let bytes: [u8; 4] = chunk.try_into().expect("sample slice should be 4 bytes");
                let sample = f32::from_le_bytes(bytes);
                let abs = sample.abs();
                if abs > peak {
                    peak = abs;
                }
                local_buffer.push((sample.clamp(-1.0, 1.0) * 32767.0) as i16);
            }

            // Update shared levels (positive floats are monotonic in bit order).
            let peak_bits = peak.to_bits();
            if user_data.is_mic {
                user_data
                    .levels
                    .mic_level
                    .fetch_max(peak_bits, Ordering::Release);
            } else {
                user_data
                    .levels
                    .system_level
                    .fetch_max(peak_bits, Ordering::Release);
            }

            // Hand the filled buffer to the encoder worker unless paused.
            if !user_data.is_paused.load(Ordering::Acquire) {
                if let Some(ref tx) = user_data.encoder_tx {
                    match tx.try_send(EncoderMessage::Write(local_buffer)) {
                        Ok(()) => return,
                        Err(TrySendError::Full(EncoderMessage::Write(buf)))
                        | Err(TrySendError::Disconnected(EncoderMessage::Write(buf))) => {
                            let _ = user_data.buffer_pool.push(buf);
                            counters.record_dropped(1);
                            return;
                        }
                        Err(_) => unreachable!(),
                    }
                }
            }
            let _ = user_data.buffer_pool.push(local_buffer);
        })
        .register()
        .map_err(|e| format!("Failed to register listener: {:?}", e))?;

    // Create audio format params - request the stable configured format
    let mut audio_info = pw::spa::param::audio::AudioInfoRaw::new();
    audio_info.set_format(pw::spa::param::audio::AudioFormat::F32LE);
    audio_info.set_rate(expected_format.0);
    audio_info.set_channels(expected_format.1 as u32);
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

    let mut params = [Pod::from_bytes(&values).expect("serialized pod bytes should be valid")];

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

    Ok(AudioStream {
        stream,
        listener,
        active,
        ready,
        negotiated,
        format_error,
        format_accepted,
    })
}

#[cfg(feature = "real-audio")]
enum SessionError {
    Fatal(String),
    Recoverable(String),
}

#[cfg(feature = "real-audio")]
struct PendingSwitch {
    original_requested: String,
    requested: String,
    fallback: Option<String>,
    stream: Option<AudioStream>,
    deadline: Instant,
}

/// State for managing mic stream that can be switched.
/// The current stream is kept live until the pending replacement is accepted
/// by the encoder, preserving mic/system track alignment.
#[cfg(feature = "real-audio")]
struct MicStreamState {
    stream: Option<AudioStream>,
    pending: Option<PendingSwitch>,
    current_device_id: Option<String>,
}

#[cfg(feature = "real-audio")]
fn create_mic_stream(
    core: pw::core::CoreRc,
    mic_id: &str,
    worker: &EncoderWorkerHandle,
    levels: Arc<SharedLevels>,
    is_paused: Arc<AtomicBool>,
    expected_format: (u32, u16),
) -> Result<AudioStream, String> {
    let props = pw::properties::properties! {
        *pw::keys::MEDIA_TYPE => "Audio",
        *pw::keys::MEDIA_CATEGORY => "Capture",
        *pw::keys::MEDIA_ROLE => "Communication",
        "target.object" => mic_id,
    };
    create_stream(
        core,
        "quinoa-mic",
        props,
        worker,
        levels,
        true,
        is_paused,
        expected_format,
    )
}

#[cfg(feature = "real-audio")]
fn assert_mic_handoff_seam(old_ready: Option<&AtomicBool>, new_ready: &AtomicBool) {
    let old = old_ready
        .map(|r| r.load(Ordering::Acquire))
        .unwrap_or(false);
    assert!(
        !old,
        "old mic stream must be deactivated (ready=false) before the new stream is marked ready (new_ready={})",
        new_ready.load(Ordering::Acquire),
    );
}

#[cfg(feature = "real-audio")]
fn process_pending_switch(
    mic_state: &Arc<Mutex<MicStreamState>>,
    core: &pw::core::CoreRc,
    mic_handle: &EncoderWorkerHandle,
    levels: Arc<SharedLevels>,
    is_paused: Arc<AtomicBool>,
    mic_expected: (u32, u16),
    event_tx: &StdSender<InternalAudioEvent>,
) {
    let mut state = mic_state.lock().unwrap_or_else(|e| e.into_inner());
    let mut pending = match state.pending.take() {
        Some(p) => p,
        None => return,
    };

    // Create the pending stream on demand and keep it inactive until negotiated.
    if pending.stream.is_none() {
        match create_mic_stream(
            core.clone(),
            &pending.requested,
            mic_handle,
            levels.clone(),
            is_paused.clone(),
            mic_expected,
        ) {
            Ok(stream) => {
                pending.stream = Some(stream);
                pending.deadline = Instant::now() + Duration::from_secs(2);
            }
            Err(_) => {
                // Stream creation failed. Keep the existing current stream live
                // and report the switch failure with its device id as fallback.
                let _ = event_tx.send(InternalAudioEvent::MicSwitchFailed {
                    requested: pending.original_requested,
                    fallback: pending.fallback,
                });
                return;
            }
        }
    }

    let stream = match pending.stream.as_mut() {
        Some(s) => s,
        None => {
            state.pending = Some(pending);
            return;
        }
    };

    // Worker failure or format error aborts this pending switch. The current
    // stream is intentionally retained and reported as the fallback.
    if mic_handle.failed.load(Ordering::Acquire) || stream.format_error.load(Ordering::Acquire) {
        let _ = event_tx.send(InternalAudioEvent::MicSwitchFailed {
            requested: pending.original_requested,
            fallback: pending.fallback,
        });
        return;
    }

    // Once the configured format is negotiated, activate the pending stream so
    // its process callback can send an Init to the encoder worker. ready stays
    // false, so audio data is silently dropped while the old stream still feeds
    // the encoder.
    if stream.negotiated.load(Ordering::Acquire) != 0 && !stream.active.load(Ordering::Acquire) {
        stream.active.store(true, Ordering::Release);
    }

    // Only swap once the encoder worker has accepted the new stream's format.
    if stream.active.load(Ordering::Acquire)
        && stream.format_accepted.load(Ordering::Acquire)
        && !mic_handle.failed.load(Ordering::Acquire)
    {
        let new_id = pending.requested.clone();
        let new_stream = pending.stream.take().expect("pending stream should exist");

        // Deactivate the old stream before marking the replacement ready.  This
        // prevents both process callbacks from being ready at the same time and
        // writing to the same encoder worker concurrently.
        if let Some(ref mut old) = state.stream {
            old.active.store(false, Ordering::Release);
            old.ready.store(false, Ordering::Release);
        }
        assert_mic_handoff_seam(state.stream.as_ref().map(|s| &*s.ready), &new_stream.ready);
        new_stream.ready.store(true, Ordering::Release);

        state.stream = Some(new_stream);
        state.current_device_id = Some(new_id.clone());

        let _ = event_tx.send(InternalAudioEvent::MicSwitched(new_id));
        return;
    }

    if Instant::now() > pending.deadline {
        // Timeout. Keep the existing current stream live and report failure.
        let _ = event_tx.send(InternalAudioEvent::MicSwitchFailed {
            requested: pending.original_requested,
            fallback: pending.fallback,
        });
        return;
    }

    // Still waiting: put the pending switch back for the next timer tick.
    state.pending = Some(pending);
}

#[cfg(feature = "real-audio")]
fn connect_and_run(
    config: &RecordingConfig,
    command_rx: Arc<Mutex<StdReceiver<AudioCommand>>>,
    event_tx: &StdSender<InternalAudioEvent>,
    mic_worker: &EncoderWorker,
    sys_worker: Option<&EncoderWorker>,
) -> Result<(), SessionError> {
    pw::init();

    let mainloop = pw::main_loop::MainLoopRc::new(None)
        .map_err(|e| SessionError::Fatal(format!("Failed to create main loop: {:?}", e)))?;
    let context = pw::context::ContextRc::new(&mainloop, None)
        .map_err(|e| SessionError::Fatal(format!("Failed to create context: {:?}", e)))?;

    // If connection fails, it might be recoverable (daemon restarting)
    let core = context
        .connect_rc(None)
        .map_err(|e| SessionError::Recoverable(format!("Failed to connect to core: {:?}", e)))?;

    // Add listener for core events (disconnect). Avoid stderr noise: emit only
    // through the audio-event channel.
    let _core_listener = core
        .add_listener_local()
        .error(|id, seq, res, message| {
            let _ = id;
            let _ = seq;
            let _ = res;
            let _ = message;
        })
        .register();

    // Shared levels state (lock-free atomics, accessed from realtime process callback)
    let levels = Arc::new(SharedLevels {
        mic_level: AtomicU32::new(0),
        system_level: AtomicU32::new(0),
        mic: StreamCounters::new(),
        sys: StreamCounters::new(),
    });

    // Shared pause state
    let is_paused = Arc::new(AtomicBool::new(false));

    // --- Microphone Stream ---
    // Track current mic state for switching
    let mic_state: Arc<Mutex<MicStreamState>> = Arc::new(Mutex::new(MicStreamState {
        stream: None,
        pending: None,
        current_device_id: config.mic_device_id.clone(),
    }));
    let mic_state_clone = mic_state.clone();

    let mic_handle = mic_worker.handle();
    let sys_handle = sys_worker.map(|w| w.handle());

    let mic_expected = (config.sample_rate, config.mic_channels);
    let sys_expected = (config.sample_rate, config.system_channels);

    // Create initial mic stream if configured. It starts inactive; the timer
    // activates it once the configured format is negotiated.
    if let Some(ref mic_id) = config.mic_device_id {
        match create_mic_stream(
            core.clone(),
            mic_id,
            &mic_handle,
            levels.clone(),
            is_paused.clone(),
            mic_expected,
        ) {
            Ok(stream_handle) => {
                if let Ok(mut state) = mic_state.lock() {
                    state.stream = Some(stream_handle);
                }
            }
            Err(e) => {
                return Err(SessionError::Recoverable(format!(
                    "Failed to create mic stream: {}",
                    e
                )));
            }
        }
    }

    // --- System Audio Stream ---
    let sys_stream: Arc<Mutex<Option<AudioStream>>> = Arc::new(Mutex::new(None));
    let sys_stream_clone = sys_stream.clone();
    if let Some(worker) = sys_handle {
        let props = pw::properties::properties! {
            *pw::keys::MEDIA_TYPE => "Audio",
            *pw::keys::MEDIA_CATEGORY => "Capture",
            *pw::keys::MEDIA_ROLE => "Music",
            *pw::keys::STREAM_CAPTURE_SINK => "true",
        };
        let stream = create_stream(
            core.clone(),
            "quinoa-sys",
            props,
            &worker,
            levels.clone(),
            false,
            is_paused.clone(),
            sys_expected,
        )
        .map_err(|e| SessionError::Recoverable(format!("Failed to create system stream: {}", e)))?;
        *sys_stream.lock().unwrap_or_else(|e| e.into_inner()) = Some(stream);
    }

    // --- Watchdog / Command / Startup / Switch Check ---
    let loop_clone = mainloop.clone();
    let event_tx_clone = event_tx.clone();
    let levels_clone = levels.clone();
    let command_rx_clone = command_rx.clone();
    let is_paused_clone = is_paused.clone();

    // We need to know if we quit because of a stop command or an error
    let stop_requested = Arc::new(Mutex::new(false));
    let stop_requested_clone = stop_requested.clone();

    // Captures the first encoder failure message so the main loop can exit fatal.
    let fatal_error: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
    let fatal_error_clone = fatal_error.clone();

    // Clone failure state for the timer closure.
    let mic_failed = mic_worker.failed.clone();
    let mic_err_msg = mic_worker.error_message.clone();
    let sys_failed = sys_worker.map(|w| w.failed.clone());
    let sys_err_msg = sys_worker.map(|w| w.error_message.clone());

    let pending_start = Arc::new(AtomicBool::new(true));
    let pending_start_clone = pending_start.clone();
    let startup_deadline = Instant::now() + Duration::from_secs(5);

    let core_clone = core.clone();
    let mic_handle_clone = mic_handle.clone();
    let levels_clone2 = levels.clone();

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
                        return;
                    }
                    AudioCommand::Pause => {
                        is_paused_clone.store(true, Ordering::Release);
                        let _ = event_tx_clone.send(InternalAudioEvent::Paused);
                    }
                    AudioCommand::Resume => {
                        is_paused_clone.store(false, Ordering::Release);
                        let _ = event_tx_clone.send(InternalAudioEvent::Resumed);
                    }
                    AudioCommand::SwitchMic(new_id) => {
                        // Queue the switch request in mic_state. The old mic stream
                        // is kept live until the replacement is negotiated and
                        // accepted by the encoder. On failure the existing current
                        // stream is retained and MicSwitchFailed is emitted with its
                        // device id as the fallback.
                        let mut state = mic_state_clone.lock().unwrap_or_else(|e| e.into_inner());
                        let fallback = state.current_device_id.clone();
                        state.pending = Some(PendingSwitch {
                            original_requested: new_id.clone(),
                            requested: new_id,
                            fallback,
                            stream: None,
                            deadline: Instant::now() + Duration::from_secs(2),
                        });
                    }
                }
            }
        }

        // If an encoder worker has failed, abort the session.
        let mut encoder_error: Option<String> = None;
        if mic_failed.load(Ordering::Acquire) {
            if let Ok(msg) = mic_err_msg.lock() {
                encoder_error = msg.clone();
            }
        }
        if encoder_error.is_none() {
            if let Some(ref sys_failed) = sys_failed {
                if sys_failed.load(Ordering::Acquire) {
                    if let Some(ref sys_err_msg) = sys_err_msg {
                        if let Ok(msg) = sys_err_msg.lock() {
                            encoder_error = msg.clone();
                        }
                    }
                }
            }
        }
        if let Some(msg) = encoder_error {
            if let Ok(mut guard) = fatal_error_clone.lock() {
                *guard = Some(msg);
            }
            loop_clone.quit();
            return;
        }

        // Startup handshake: don't announce Started until all configured streams
        // have negotiated the configured format and the encoder has accepted it.
        if pending_start_clone.load(Ordering::Acquire) {
            let (mic_negotiated, mic_format_error, mic_accepted) = mic_state_clone
                .lock()
                .ok()
                .map(|s| {
                    s.stream.as_ref().map(|st| (
                        st.negotiated.load(Ordering::Acquire) != 0,
                        st.format_error.load(Ordering::Acquire),
                        st.format_accepted.load(Ordering::Acquire),
                    )).unwrap_or((true, false, true))
                })
                .unwrap_or((true, false, true));
            let (sys_negotiated, sys_format_error, sys_accepted) = sys_stream_clone
                .lock()
                .ok()
                .map(|s| {
                    s.as_ref().map(|st| (
                        st.negotiated.load(Ordering::Acquire) != 0,
                        st.format_error.load(Ordering::Acquire),
                        st.format_accepted.load(Ordering::Acquire),
                    )).unwrap_or((true, false, true))
                })
                .unwrap_or((true, false, true));

            let format_error = mic_format_error || sys_format_error;
            let all_negotiated = mic_negotiated && sys_negotiated;

            if all_negotiated && !format_error {
                // Activate each configured stream so the encoder worker can be
                // initialized and accept the format.
                if let Ok(mut state) = mic_state_clone.lock() {
                    if let Some(ref mut st) = state.stream {
                        st.active.store(true, Ordering::Release);
                        st.ready.store(true, Ordering::Release);
                    }
                }
                if let Ok(mut sys) = sys_stream_clone.lock() {
                    if let Some(ref mut st) = sys.as_mut() {
                        st.active.store(true, Ordering::Release);
                        st.ready.store(true, Ordering::Release);
                    }
                }
            }

            let all_accepted = mic_accepted && sys_accepted;

            if all_accepted && !format_error {
                let _ = event_tx_clone.send(InternalAudioEvent::Started);
                pending_start_clone.store(false, Ordering::Release);
            } else if format_error || Instant::now() > startup_deadline {
                if let Ok(mut guard) = fatal_error_clone.lock() {
                    *guard = Some(
                        "Audio streams failed to negotiate the configured format within the startup deadline".to_string(),
                    );
                }
                loop_clone.quit();
                return;
            }
        }

        // Process pending mic switch: create stream if needed, wait for encoder
        // acceptance, fall back on format error or timeout, and only emit events
        // once the replacement has actually been accepted.
        process_pending_switch(
            &mic_state_clone,
            &core_clone,
            &mic_handle_clone,
            levels_clone2.clone(),
            is_paused_clone.clone(),
            mic_expected,
            &event_tx_clone,
        );

        if !pending_start_clone.load(Ordering::Acquire) {
            // Account for switch gaps when a configured stream is inactive.
            if let Ok(state) = mic_state_clone.lock() {
                if state.stream.as_ref().map(|s| !s.active.load(Ordering::Acquire)).unwrap_or(false) {
                    levels_clone2.mic.record_switch_gap(1);
                }
            }
            if let Ok(sys) = sys_stream_clone.lock() {
                if sys.as_ref().map(|s| !s.active.load(Ordering::Acquire)).unwrap_or(false) {
                    levels_clone2.sys.record_switch_gap(1);
                }
            }

            let mic_delta = levels_clone2.mic.take_delta();
            let sys_delta = levels_clone2.sys.take_delta();
            if mic_delta.has_loss() || sys_delta.has_loss() {
                if let Ok(mut guard) = fatal_error_clone.lock() {
                    *guard = Some(format!(
                        "Audio alignment lost: mic_delta={:?} sys_delta={:?}",
                        mic_delta, sys_delta
                    ));
                }
                loop_clone.quit();
                return;
            }
        }

        // Send levels (atomic swap to read and reset)
        let mic_peak = f32::from_bits(levels_clone.mic_level.swap(0, Ordering::Acquire));
        let sys_peak = f32::from_bits(levels_clone.system_level.swap(0, Ordering::Acquire));

        let _ = event_tx_clone.send(InternalAudioEvent::Levels {
            mic: mic_peak,
            system: sys_peak,
        });
    });

    let timeout = Duration::from_millis(100);
    timer.update_timer(Some(timeout), Some(timeout));

    mainloop.run();

    // Encoder failure is fatal.
    if let Ok(err) = fatal_error.lock() {
        if let Some(msg) = err.as_ref() {
            return Err(SessionError::Fatal(msg.clone()));
        }
    }

    // Check if we're stopping
    if let Ok(stop) = stop_requested.lock() {
        if *stop {
            return Ok(());
        }
    }

    // If we get here and didn't request stop, it means the mainloop quit unexpectedly
    Err(SessionError::Recoverable(
        "PipeWire mainloop exited unexpectedly".to_string(),
    ))
}

#[cfg(feature = "real-audio")]
fn run_audio_thread(
    config: RecordingConfig,
    command_rx: StdReceiver<AudioCommand>,
    event_tx: StdSender<InternalAudioEvent>,
) -> Result<(), String> {
    let command_rx = Arc::new(Mutex::new(command_rx));

    let output_dir = PathBuf::from(&config.output_dir);
    if !output_dir.exists() {
        std::fs::create_dir_all(&output_dir)
            .map_err(|e| format!("Failed to create output dir: {:?}", e))?;
    }

    let mic_output_path = output_dir.join("microphone.wav");
    let sys_output_path = output_dir.join("system.wav");

    // Spawn persistent encoder workers that survive PipeWire reconnects and mic switches.
    let mic_worker = EncoderWorker::new(mic_output_path);
    let sys_worker = if config.system_audio {
        Some(EncoderWorker::new(sys_output_path))
    } else {
        None
    };

    let result = loop {
        match connect_and_run(
            &config,
            command_rx.clone(),
            &event_tx,
            &mic_worker,
            sys_worker.as_ref(),
        ) {
            Ok(()) => {
                // Clean stop; finalize workers before returning.
                break Ok(());
            }
            Err(SessionError::Fatal(e)) => {
                // Fatal error, give up.
                break Err(e);
            }
            Err(SessionError::Recoverable(_e)) => {
                // Recoverable, notify and retry. Check for stop between retries
                // so the session can terminate even during repeated PipeWire
                // connection failures.
                let _ = event_tx.send(InternalAudioEvent::PipeWireDisconnected);

                let mut stop = false;
                let mut waited = 0;
                while waited < 20 {
                    match command_rx
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .recv_timeout(Duration::from_millis(100))
                    {
                        Ok(AudioCommand::Stop)
                        | Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                            stop = true;
                            break;
                        }
                        Ok(_) => {}
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => waited += 1,
                    }
                }
                if stop {
                    break Ok(());
                }
                if waited >= 20 {
                    let _ = event_tx.send(InternalAudioEvent::PipeWireDisconnected);
                }
            }
        }
    };

    // Finalize and capture any error reported by the worker (including WavWriter
    // finalization errors). Thread panics take second seat to the worker's own
    // error message because it is more specific.
    let mic_result = mic_worker.finalize();
    let sys_result = if let Some(worker) = sys_worker {
        Some(worker.finalize())
    } else {
        None
    };

    let mut finalize_error: Option<String> = None;
    if let Err(e) = mic_result {
        finalize_error = Some(e);
    }
    if let Some(Err(e)) = sys_result {
        finalize_error = match finalize_error {
            Some(existing) => Some(format!("{}; system: {}", existing, e)),
            None => Some(e),
        };
    }

    match result {
        Ok(()) => {
            if let Some(msg) = finalize_error {
                return Err(msg);
            }
            Ok(())
        }
        Err(e) => {
            if let Some(msg) = finalize_error {
                return Err(format!("{}; finalize error: {}", e, msg));
            }
            Err(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc::channel;
    use std::time::Duration;

    static TEST_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

    #[cfg(not(feature = "real-audio"))]
    fn test_config() -> RecordingConfig {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        let output_dir = std::env::temp_dir()
            .join(format!("quinoa_audio_session_test_{}", id))
            .to_string_lossy()
            .to_string();
        let _ = std::fs::create_dir_all(&output_dir);
        RecordingConfig::new(output_dir, None, false, None, None, None)
    }

    #[cfg(not(feature = "real-audio"))]
    #[test]
    fn test_stop_returns_ok_for_clean_mock_session() {
        let mut session = start_recording_impl(test_config()).unwrap();
        std::thread::sleep(Duration::from_millis(50));
        assert!(session.shutdown_sync().is_none());
        assert!(session.command_tx.is_none());
        assert!(session.thread_handle.is_none());
    }

    #[test]
    fn test_stop_propagates_thread_error() {
        let (tx, _rx) = channel::<AudioCommand>();
        let (_event_tx, event_rx) = channel::<InternalAudioEvent>();
        let handle = thread::spawn(|| Err::<(), String>("encoder finalize failed".into()));
        let mut session = RecordingSession {
            command_tx: Some(tx),
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: Some(handle),
            pending_events: Vec::new(),
        };
        assert!(session.shutdown_sync().is_some());
    }

    #[test]
    fn test_stop_raises_queued_event_error() {
        let (tx, _rx) = channel::<AudioCommand>();
        let (event_tx, event_rx) = channel::<InternalAudioEvent>();
        let _ = event_tx.send(InternalAudioEvent::Error("mic exploded".into()));
        drop(event_tx);
        let handle = thread::spawn(|| Ok::<(), String>(()));
        let mut session = RecordingSession {
            command_tx: Some(tx),
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: Some(handle),
            pending_events: Vec::new(),
        };
        assert!(session.shutdown_sync().is_some());
    }

    #[test]
    fn test_drop_signals_cleanup_without_blocking() {
        let (tx, rx) = channel::<AudioCommand>();
        let (_event_tx, event_rx) = channel::<InternalAudioEvent>();
        let stopped = Arc::new(AtomicBool::new(false));
        let stopped_clone = stopped.clone();
        let handle = thread::spawn(move || loop {
            match rx.recv_timeout(Duration::from_millis(50)) {
                Ok(AudioCommand::Stop) => {
                    stopped_clone.store(true, Ordering::Relaxed);
                    break Ok::<(), String>(());
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break Ok(()),
                _ => {}
            }
        });
        {
            let session = RecordingSession {
                command_tx: Some(tx),
                event_rx: Some(Mutex::new(event_rx)),
                thread_handle: Some(handle),
                pending_events: Vec::new(),
            };
            let start = std::time::Instant::now();
            drop(session);
            // Drop must not synchronously join the audio thread.
            assert!(start.elapsed() < Duration::from_millis(100));
        }
        let deadline = std::time::Instant::now() + Duration::from_secs(2);
        while !stopped.load(Ordering::Relaxed) && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(stopped.load(Ordering::Relaxed));
    }

    #[test]
    fn test_shutdown_sync_is_idempotent() {
        let session = RecordingSession {
            command_tx: None,
            event_rx: None,
            thread_handle: None,
            pending_events: Vec::new(),
        };
        // Cannot mutate a moved value, so use a helper closure.
        let mut session = session;
        assert!(session.shutdown_sync().is_none());
    }

    #[test]
    fn test_shutdown_sync_returns_queued_event_error() {
        let (tx, _rx) = channel::<AudioCommand>();
        let (event_tx, event_rx) = channel::<InternalAudioEvent>();
        let _ = event_tx.send(InternalAudioEvent::Error("mic exploded".into()));
        drop(event_tx);
        let handle = thread::spawn(|| Ok::<(), String>(()));
        let mut session = RecordingSession {
            command_tx: Some(tx),
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: Some(handle),
            pending_events: Vec::new(),
        };
        let err = session.shutdown_sync().expect("expected queued error");
        assert!(err.contains("mic exploded"));
    }

    #[test]
    fn test_shutdown_sync_prefers_thread_error() {
        let (tx, _rx) = channel::<AudioCommand>();
        let (event_tx, event_rx) = channel::<InternalAudioEvent>();
        let _ = event_tx.send(InternalAudioEvent::Error("queued".into()));
        drop(event_tx);
        let handle = thread::spawn(|| Err::<(), String>("thread died".into()));
        let mut session = RecordingSession {
            command_tx: Some(tx),
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: Some(handle),
            pending_events: Vec::new(),
        };
        let err = session.shutdown_sync().expect("expected error");
        assert!(err.contains("thread died"), "unexpected error: {}", err);
    }

    #[test]
    fn test_stopped_event_pollable_after_shutdown() {
        let (tx, rx) = channel::<AudioCommand>();
        let (event_tx, event_rx) = channel::<InternalAudioEvent>();
        let stopped_event_tx = event_tx.clone();
        let handle = thread::spawn(move || loop {
            match rx.recv_timeout(Duration::from_millis(50)) {
                Ok(AudioCommand::Stop) => {
                    let _ = stopped_event_tx.send(InternalAudioEvent::Stopped);
                    break Ok::<(), String>(());
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break Ok(()),
                _ => {}
            }
        });
        let mut session = RecordingSession {
            command_tx: Some(tx),
            event_rx: Some(Mutex::new(event_rx)),
            thread_handle: Some(handle),
            pending_events: Vec::new(),
        };
        assert!(session.shutdown_sync().is_none());
        let events = session.poll_events().unwrap();
        assert!(
            events.iter().any(|e| e.type_ == "stopped"),
            "Stopped event should remain pollable after stop/shutdown"
        );
    }

    #[cfg(feature = "real-audio")]
    #[test]
    fn test_encoder_worker_finalize_ok() {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("quinoa_worker_ok_{}.wav", id));
        let worker = EncoderWorker::new(path.clone());
        worker
            .tx
            .try_send(EncoderMessage::Init {
                sample_rate: 48000,
                channels: 1,
                format_accepted: Arc::new(AtomicBool::new(false)),
            })
            .unwrap();
        worker
            .tx
            .try_send(EncoderMessage::Write(vec![1000i16; 1024]))
            .unwrap();
        assert!(worker.finalize().is_ok());

        let reader = hound::WavReader::open(&path).unwrap();
        assert_eq!(reader.spec().sample_rate, 48000);
        assert_eq!(reader.spec().channels, 1);
    }

    #[cfg(feature = "real-audio")]
    #[test]
    fn test_encoder_worker_propagates_init_error() {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("quinoa_worker_bad_{}", id));
        std::fs::create_dir_all(&path).unwrap();
        let worker = EncoderWorker::new(path);
        worker
            .tx
            .try_send(EncoderMessage::Init {
                sample_rate: 48000,
                channels: 2,
                format_accepted: Arc::new(AtomicBool::new(false)),
            })
            .unwrap();
        std::thread::sleep(Duration::from_millis(50));
        let result = worker.finalize();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("Encoder init failed") || err.contains("WAV"));
    }

    #[cfg(feature = "real-audio")]
    #[test]
    fn test_encoder_worker_format_change_error() {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("quinoa_worker_fmt_{}.wav", id));
        let worker = EncoderWorker::new(path);
        worker
            .tx
            .try_send(EncoderMessage::Init {
                sample_rate: 48000,
                channels: 2,
                format_accepted: Arc::new(AtomicBool::new(false)),
            })
            .unwrap();
        worker
            .tx
            .try_send(EncoderMessage::Init {
                sample_rate: 48000,
                channels: 1,
                format_accepted: Arc::new(AtomicBool::new(false)),
            })
            .unwrap();
        let result = worker.finalize();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("format changed"));
    }

    #[cfg(feature = "real-audio")]
    #[test]
    fn test_encoder_worker_sets_format_accepted_ack() {
        let id = TEST_ID.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("quinoa_worker_ack_{}.wav", id));
        let worker = EncoderWorker::new(path);
        let ack = Arc::new(AtomicBool::new(false));
        worker
            .tx
            .try_send(EncoderMessage::Init {
                sample_rate: 48000,
                channels: 1,
                format_accepted: ack.clone(),
            })
            .unwrap();
        worker
            .tx
            .try_send(EncoderMessage::Write(vec![0i16; 64]))
            .unwrap();
        std::thread::sleep(Duration::from_millis(50));
        assert!(
            ack.load(Ordering::Acquire),
            "format_accepted ack was not set"
        );
        assert!(worker.finalize().is_ok());
    }

    #[cfg(feature = "real-audio")]
    #[test]
    fn test_mic_handoff_seam_allows_deactivated_old() {
        let old = AtomicBool::new(false);
        let new = AtomicBool::new(false);
        assert_mic_handoff_seam(Some(&old), &new);
    }

    #[cfg(feature = "real-audio")]
    #[test]
    #[should_panic(expected = "old mic stream must be deactivated")]
    fn test_mic_handoff_seam_panics_when_old_ready() {
        let old = AtomicBool::new(true);
        let new = AtomicBool::new(false);
        assert_mic_handoff_seam(Some(&old), &new);
    }
}
