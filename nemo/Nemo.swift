// Nemo — Ristretto's face on the desktop.
//
// A small window that floats above every application and every Space, so it
// is there whatever you are looking at. Hold the mouse on it to talk; let go
// and it writes back what it heard and what Nemo said.
//
// Three deliberate choices:
//
// Non-activating panel. Clicking Nemo must not pull focus out of whatever you
// were doing — an assistant that steals your cursor is an interruption, not a
// presence.
//
// Hold to talk, no wake word. The microphone opens only while the mouse is
// down, so there is no always-listening window in which a room, a call or a
// video can be recorded. It also means nobody has to trust a voice-activity
// detector.
//
// It only ever asks Nemo. Nemo has no tools and no board access of its own; it
// posts to the dashboard's /voice and /chat and renders the answer. Anything
// that changes the world still happens behind the approval gate.

import AVFoundation
import AppKit

// MARK: - Configuration

struct Config {
    // The dashboard this Nemo belongs to. Defaults to the tailnet address the
    // service binds; RIS_DASH overrides for a laptop or a test instance.
    static var dashURL: String {
        if let explicit = ProcessInfo.processInfo.environment["RIS_DASH"], !explicit.isEmpty {
            return explicit
        }
        // Written by the installer, because the address is a fact about this
        // machine's tailnet and has no business in the repository.
        let file = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".ristretto/dash-url")
        if let text = try? String(contentsOf: file, encoding: .utf8) {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { return trimmed }
        }
        return "http://127.0.0.1:8787"
    }
    // How often to ask whether anything is waiting on a person. Slow on
    // purpose: this is a glance, not a poll for work.
    static let watchInterval: TimeInterval = 20
}

// MARK: - Talking to Nemo

/// Swift's Result needs a Failure conforming to Error, and what comes back
/// from Nemo is a sentence, not an exception. This says exactly that.
enum Answer {
    case said(String)
    case failed(String)
}

final class Backend {
    private let session = URLSession(configuration: .default)

    private func request(_ path: String, body: Data, contentType: String) -> URLRequest {
        var request = URLRequest(url: URL(string: Config.dashURL + path)!)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        // The dashboard's mutating routes are same-origin only. A desktop
        // client is not a browser, so it says who it is the way a page would.
        //
        // Origin only. Setting Host by hand looked helpful and was the bug:
        // URL.host drops the port, so the header said "...ts.net" while the
        // Origin implied "...ts.net:8787", the server compared the two and
        // refused its own client. URLSession sets Host correctly on its own.
        request.setValue(Config.dashURL, forHTTPHeaderField: "Origin")
        request.timeoutInterval = 180
        return request
    }

    func hear(_ audio: Data, done: @escaping (Answer) -> Void) {
        session.dataTask(with: request("/voice", body: audio, contentType: "application/octet-stream")) { data, _, error in
            if let error { return done(.failed(error.localizedDescription)) }
            guard let data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return done(.failed("could not read the reply")) }
            if let text = json["text"] as? String, !text.isEmpty { return done(.said(text)) }
            done(.failed((json["detail"] as? String) ?? "nothing heard"))
        }.resume()
    }

    func ask(_ message: String, done: @escaping (Answer) -> Void) {
        let body = try! JSONSerialization.data(withJSONObject: ["message": message])
        session.dataTask(with: request("/chat", body: body, contentType: "application/json")) { data, _, error in
            if let error { return done(.failed(error.localizedDescription)) }
            guard let data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return done(.failed("could not read the reply")) }
            if let text = json["text"] as? String, !text.isEmpty { return done(.said(text)) }
            done(.failed("Nemo said nothing"))
        }.resume()
    }

    /// How many decisions are waiting on a person, for the badge.
    func waiting(done: @escaping (Int) -> Void) {
        var request = URLRequest(url: URL(string: Config.dashURL + "/nemo/state")!)
        request.timeoutInterval = 15
        session.dataTask(with: request) { data, _, _ in
            guard let data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let count = json["waiting"] as? Int
            else { return done(0) }
            done(count)
        }.resume()
    }
}

// MARK: - Listening

final class Ear {
    private let engine = AVAudioEngine()
    private var file: AVAudioFile?
    private var url: URL?

    /// True if the microphone actually opened. Nemo says so rather than
    /// pretending to listen.
    func start() -> Bool {
        let input = engine.inputNode
        let format = input.inputFormat(forBus: 0)
        guard format.sampleRate > 0 else { return false }
        let target = FileManager.default.temporaryDirectory
            .appendingPathComponent("nemo-\(UUID().uuidString).wav")
        do {
            file = try AVAudioFile(forWriting: target, settings: format.settings)
        } catch {
            return false
        }
        url = target
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            try? self?.file?.write(from: buffer)
        }
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            return false
        }
        return true
    }

    /// Stops and hands back the recording, or nil if there was nothing usable.
    func stop() -> Data? {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        file = nil
        defer { url = nil }
        guard let url else { return nil }
        let data = try? Data(contentsOf: url)
        try? FileManager.default.removeItem(at: url)
        // A tap shorter than a syllable is a misclick, not a sentence.
        return (data?.count ?? 0) > 8000 ? data : nil
    }
}

// MARK: - The face

final class FaceView: NSView {
    var onPressChanged: ((Bool) -> Void)?
    var listening = false { didSet { needsDisplay = true } }
    var thinking = false { didSet { needsDisplay = true } }
    var waiting = 0 { didSet { needsDisplay = true } }

    override func draw(_ rect: NSRect) {
        let body = NSBezierPath(ovalIn: bounds.insetBy(dx: 4, dy: 4))
        // Listening is the one state that must be unmistakable from across a
        // room: the microphone is open and you should know without reading.
        let fill: NSColor = listening
            ? NSColor.systemRed
            : (thinking ? NSColor.systemOrange : NSColor(calibratedRed: 0.11, green: 0.44, blue: 0.42, alpha: 1))
        fill.setFill()
        body.fill()
        NSColor.white.withAlphaComponent(0.85).setStroke()
        body.lineWidth = 2
        body.stroke()

        let mark = listening ? "●" : (thinking ? "…" : "R")
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 20, weight: .semibold),
            .foregroundColor: NSColor.white,
        ]
        let size = mark.size(withAttributes: attrs)
        mark.draw(at: NSPoint(x: bounds.midX - size.width / 2, y: bounds.midY - size.height / 2),
                  withAttributes: attrs)

        // Something needs a person. A count, not a dot: one waiting decision
        // and six are different situations.
        if waiting > 0 {
            let badge = NSRect(x: bounds.maxX - 20, y: bounds.maxY - 20, width: 18, height: 18)
            NSColor.systemOrange.setFill()
            NSBezierPath(ovalIn: badge).fill()
            let text = "\(waiting)"
            let badgeAttrs: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: 11, weight: .bold),
                .foregroundColor: NSColor.black,
            ]
            let textSize = text.size(withAttributes: badgeAttrs)
            text.draw(at: NSPoint(x: badge.midX - textSize.width / 2, y: badge.midY - textSize.height / 2),
                      withAttributes: badgeAttrs)
        }
    }

    override func mouseDown(with event: NSEvent) { onPressChanged?(true) }
    override func mouseUp(with event: NSEvent) { onPressChanged?(false) }
}

// MARK: - The app

final class Nemo: NSObject, NSApplicationDelegate {
    private var panel: NSPanel!
    private var face: FaceView!
    private var bubble: NSTextField!
    private let backend = Backend()
    private let ear = Ear()
    private var timer: Timer?

    func applicationDidFinishLaunching(_ note: Notification) {
        let width: CGFloat = 340, faceSize: CGFloat = 56
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let frame = NSRect(x: screen.maxX - width - 24, y: screen.minY + 24, width: width, height: 200)

        panel = NSPanel(contentRect: frame,
                        styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered,
                        defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        // Above normal windows but below the menu bar, and present on every
        // Space including full-screen apps — otherwise "always visible" means
        // "visible until you go full screen", which is when you are working.
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isMovableByWindowBackground = true

        let root = NSView(frame: NSRect(origin: .zero, size: frame.size))

        bubble = NSTextField(wrappingLabelWithString: "")
        bubble.frame = NSRect(x: 0, y: faceSize + 12, width: width, height: frame.height - faceSize - 12)
        bubble.isEditable = false
        bubble.isSelectable = true
        bubble.drawsBackground = true
        bubble.backgroundColor = NSColor(calibratedWhite: 0.08, alpha: 0.92)
        bubble.textColor = .white
        bubble.font = .systemFont(ofSize: 13)
        bubble.wantsLayer = true
        bubble.layer?.cornerRadius = 10
        bubble.isHidden = true
        root.addSubview(bubble)

        face = FaceView(frame: NSRect(x: width - faceSize, y: 0, width: faceSize, height: faceSize))
        face.onPressChanged = { [weak self] down in down ? self?.beginListening() : self?.endListening() }
        root.addSubview(face)

        panel.contentView = root
        panel.orderFrontRegardless()

        say("Hold to talk.")
        timer = Timer.scheduledTimer(withTimeInterval: Config.watchInterval, repeats: true) { [weak self] _ in
            self?.backend.waiting { count in DispatchQueue.main.async { self?.face.waiting = count } }
        }
        timer?.fire()
    }

    private func beginListening() {
        guard ear.start() else {
            return say("I could not open the microphone. Check System Settings → Privacy → Microphone.")
        }
        face.listening = true
        say("Listening…")
    }

    private func endListening() {
        face.listening = false
        guard let audio = ear.stop() else { return say("That was too short to hear.") }
        face.thinking = true
        backend.hear(audio) { [weak self] heard in
            DispatchQueue.main.async {
                switch heard {
                case .failed(let why):
                    self?.face.thinking = false
                    self?.say("I did not catch that — \(why)")
                case .said(let text):
                    // What it heard, before what it thinks: a wrong
                    // transcription should be obvious immediately rather than
                    // explaining a strange answer afterwards.
                    self?.say("“\(text)”\n\n…")
                    self?.backend.ask(text) { reply in
                        DispatchQueue.main.async {
                            self?.face.thinking = false
                            switch reply {
                            case .said(let answer): self?.say("“\(text)”\n\n\(answer)")
                            case .failed(let why): self?.say("“\(text)”\n\nRis did not answer: \(why)")
                            }
                        }
                    }
                }
            }
        }
    }

    private func say(_ text: String) {
        bubble.stringValue = text
        bubble.isHidden = false
        bubble.sizeToFit()
        let width = panel.frame.width
        let height = min(max(bubble.frame.height + 24, 40), 420)
        bubble.frame = NSRect(x: 0, y: 68, width: width, height: height)
        var frame = panel.frame
        let newHeight = height + 68
        frame.origin.y += frame.height - newHeight
        frame.size.height = newHeight
        panel.setFrame(frame, display: true)
    }
}

let app = NSApplication.shared
let nemo = Nemo()
app.delegate = nemo
// .accessory: no Dock icon, no menu bar. Nemo is furniture, not an app you
// switch to.
app.setActivationPolicy(.accessory)
app.run()
