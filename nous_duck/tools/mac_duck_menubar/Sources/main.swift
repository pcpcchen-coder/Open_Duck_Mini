// 鴨子 Nous：Mac 選單列上的鴨子圖示，給「鴨子用的 Nous」（127.0.0.1:8791）和鴨子（Pi）的設定頁一個入口。
//
// 做的事：顯示狀態（Nous、AI 引擎、ChatGPT 登入、即時語音、鴨子連線、通道、Pi 設定頁）；
//         在視窗裡打開 8791 現有的設定畫面、Pi 現有的設定頁（不重寫、不轉手）；打開 log；重新啟動 8791 的 Nous（先確認）。
// 不做的事：不動 /Applications/Nous.app 與 8787；不讀金鑰、.env、憑證；不碰 Pi 上的服務與舵機；
//          網頁要開的外部連結（登入頁等）一律交給系統瀏覽器；兩個視窗都不給麥克風與鏡頭。

import AppKit
import WebKit

let nousPort = Int(ProcessInfo.processInfo.environment["NOUS_DUCK_PORT"] ?? "") ?? 8791
let piPort = 8081
let defaultPiHost = "duck-pi4.local"
let nousAgent = "com.nousduck.nous-dev"
let tunnelAgent = "com.nousduck.duck-tunnel"
let logDir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/nous-duck-dev")

var piHost: String {
  get { UserDefaults.standard.string(forKey: "piHost").flatMap(normalizedPiHost) ?? defaultPiHost }
  set { UserDefaults.standard.set(newValue, forKey: "piHost") }
}

// MARK: - 狀態收集（背景執行，結果回主執行緒）

struct Snapshot {
  var nousAgentState: AgentState = .notLoaded
  var tunnelAgentState: AgentState = .notLoaded
  var nous = NousSnapshot()
  var tunnelLogTail: String?
  var piReachable: Bool?
}

func launchctlState(_ label: String) -> AgentState {
  let p = Process()
  p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
  p.arguments = ["print", "gui/\(getuid())/\(label)"]
  let out = Pipe()
  p.standardOutput = out
  p.standardError = Pipe()
  do { try p.run() } catch { return .notLoaded }
  let data = out.fileHandleForReading.readDataToEndOfFile()
  p.waitUntilExit()
  return parseLaunchctl(output: String(decoding: data, as: UTF8.self), exitCode: p.terminationStatus)
}

/// 同步 GET（只在背景執行緒用）；timeout 秒內沒回就當失敗。
func httpGet(_ url: URL, timeout: TimeInterval) -> (Data?, String?) {
  var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
  request.setValue("application/json", forHTTPHeaderField: "Accept")
  let done = DispatchSemaphore(value: 0)
  var result: (Data?, String?) = (nil, nil)
  let task = URLSession.shared.dataTask(with: request) { data, response, error in
    if let error { result = (nil, error.localizedDescription) }
    else if let http = response as? HTTPURLResponse, http.statusCode != 200 { result = (nil, "HTTP \(http.statusCode)") }
    else { result = (data, nil) }
    done.signal()
  }
  task.resume()
  if done.wait(timeout: .now() + timeout + 1) == .timedOut { task.cancel(); return (nil, "逾時") }
  return result
}

func tail(of file: URL, bytes: Int = 2048) -> String? {
  guard let h = try? FileHandle(forReadingFrom: file) else { return nil }
  defer { try? h.close() }
  let size = (try? h.seekToEnd()) ?? 0
  try? h.seek(toOffset: size > UInt64(bytes) ? size - UInt64(bytes) : 0)
  return String(decoding: h.readDataToEndOfFile(), as: UTF8.self)
}

func collect(host: String) -> Snapshot {
  var s = Snapshot()
  let group = DispatchGroup()
  let q = DispatchQueue.global(qos: .userInitiated)
  let lock = NSLock()
  func run(_ work: @escaping () -> Void) { group.enter(); q.async { work(); group.leave() } }
  run { let v = launchctlState(nousAgent); lock.lock(); s.nousAgentState = v; lock.unlock() }
  run { let v = launchctlState(tunnelAgent); lock.lock(); s.tunnelAgentState = v; lock.unlock() }
  run {
    let (settings, err1) = httpGet(URL(string: "http://127.0.0.1:\(nousPort)/api/settings")!, timeout: 3)
    let (integrations, _) = httpGet(URL(string: "http://127.0.0.1:\(nousPort)/api/integrations/status")!, timeout: 3)
    lock.lock()
    s.nous = NousSnapshot(settings: jsonObject(settings), integrations: jsonObject(integrations), error: err1)
    lock.unlock()
  }
  run {
    let (data, _) = httpGet(URL(string: "http://\(host):\(piPort)/healthz")!, timeout: 3)
    let ok = data.map { String(decoding: $0, as: UTF8.self).hasPrefix("ok") } ?? false
    lock.lock(); s.piReachable = ok; lock.unlock()
  }
  run { let v = tail(of: logDir.appendingPathComponent("tunnel.log")); lock.lock(); s.tunnelLogTail = v; lock.unlock() }
  group.wait()
  return s
}

// MARK: - 網頁視窗

/// 網頁要開的新視窗（window.open、target=_blank）：先開 about:blank 再換網址的也接得到；網址一出現就交給系統瀏覽器。
final class PopupCatcher: NSObject, WKNavigationDelegate {
  let webView: WKWebView
  var onDone: (() -> Void)?

  init(configuration: WKWebViewConfiguration) {
    webView = WKWebView(frame: .zero, configuration: configuration)
    super.init()
    webView.navigationDelegate = self
  }

  func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
    if let url = action.request.url, url.scheme == "http" || url.scheme == "https" {
      NSWorkspace.shared.open(url)
      decisionHandler(.cancel)
      onDone?()
      return
    }
    decisionHandler(.allow)
  }
}

final class WebWindow: NSObject, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
  enum Kind { case nous, duck }

  let kind: Kind
  let window: NSWindow
  let webView: WKWebView
  private var popups: [PopupCatcher] = []
  var settingsOpened = false
  var lastSeenPi: Date?

  init(kind: Kind) {
    self.kind = kind
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .default()
    webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 900, height: 760), configuration: config)
    window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 760), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
    super.init()
    window.title = kind == .nous ? "鴨子用的 Nous：設定" : "鴨子設定"
    window.contentView = webView
    window.isReleasedWhenClosed = false
    window.delegate = self
    window.setFrameAutosaveName(kind == .nous ? "NousDuckNousSettings" : "NousDuckPiSettings")
    if window.frame.origin == .zero { window.center() }
    webView.navigationDelegate = self
    webView.uiDelegate = self
  }

  var targetURL: URL {
    kind == .nous ? URL(string: "http://localhost:\(nousPort)/")! : URL(string: "http://\(piHost):\(piPort)/")!
  }

  func show() {
    webView.load(URLRequest(url: targetURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8))
    NSApp.activate(ignoringOtherApps: true)
    window.makeKeyAndOrderFront(nil)
  }

  private func allowedInside(_ url: URL) -> Bool {
    if url.absoluteString == "about:blank" { return true }
    guard url.scheme == "http", let host = url.host?.lowercased() else { return false }
    switch kind {
    case .nous: return (host == "localhost" || host == "127.0.0.1") && url.port == nousPort
    case .duck: return host == piHost && url.port == piPort
    }
  }

  func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
    guard let url = action.request.url else { decisionHandler(.cancel); return }
    if url.scheme == "duckmenu" { decisionHandler(.cancel); show(); return }
    // 頁面自己的 iframe、子資源由頁面的 CSP 管；這裡只管主框架換頁。
    if action.targetFrame?.isMainFrame == false || allowedInside(url) { decisionHandler(.allow); return }
    if url.scheme == "http" || url.scheme == "https" { NSWorkspace.shared.open(url) }
    decisionHandler(.cancel)
  }

  func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
    if let url = action.request.url, url.scheme == "http" || url.scheme == "https" {
      NSWorkspace.shared.open(url)
      return nil
    }
    // about:blank 先開、之後才設網址（Nous 的 ChatGPT 方案登入就是這樣）：給一個看不見的 WebView 接住，網址一出現就交給系統瀏覽器。
    let catcher = PopupCatcher(configuration: configuration)
    catcher.onDone = { [weak self, weak catcher] in self?.popups.removeAll { $0 === catcher } }
    popups.append(catcher)
    return catcher.webView
  }

  // 設定視窗不需要麥克風與鏡頭；頁面要也不給（對話請用鴨子或 Nous 的頁面）。
  @available(macOS 12.0, *)
  func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
    decisionHandler(.deny)
  }

  func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
    let alert = NSAlert()
    alert.messageText = message
    alert.beginSheetModal(for: window) { _ in completionHandler() }
  }

  func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
    let alert = NSAlert()
    alert.messageText = message
    alert.addButton(withTitle: "好")
    alert.addButton(withTitle: "取消")
    alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    snapshotIfRequested()
    guard webView.url?.absoluteString != "about:blank" else { return }
    switch kind {
    case .duck:
      lastSeenPi = Date()
      window.subtitle = ""
    case .nous:
      // 8791 的瀏覽器版頁面沒有網址可以直接開設定畫面；按頁面上既有的「設定」按鈕（id=conversation-settings，在對話面板裡）。
      // 找不到按鈕（AIOS 改了頁面）時不猜，標題列告訴使用者怎麼自己開。
      // 頁面載完後還要等它向核心拿到設定才畫得出設定畫面，所以每 0.4 秒按一次，直到看到設定畫面（最多 8 秒）。
      let js = """
      const isOpen = () => ['設定', 'Settings'].includes(document.querySelector('.surface-header .eyebrow')?.textContent?.trim());
      for (let i = 0; i < 20; i++) {
        const b = document.getElementById('conversation-settings');
        if (!b) return 'missing';
        if (isOpen()) return 'open';
        b.click();
        await new Promise((r) => setTimeout(r, 400));
      }
      return isOpen() ? 'open' : 'timeout';
      """
      window.subtitle = "正在打開設定…"
      webView.callAsyncJavaScript(js, arguments: [:], in: nil, in: .page) { [weak self] result in
        let opened = (try? result.get()) as? String == "open"
        self?.window.subtitle = opened ? "" : "沒有自動打開設定：在頁面上打字「設定」再按 Enter"
        self?.settingsOpened = opened
      }
    }
  }

  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { showError(error) }
  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { showError(error) }

  private func showError(_ error: Error) {
    let ns = error as NSError
    if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
    if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return } // 被我們取消的換頁（交給系統瀏覽器）
    switch kind {
    case .duck:
      window.subtitle = "連不到"
      webView.loadHTMLString(offlinePageHTML(host: piHost, port: piPort, reason: ns.localizedDescription, lastSeen: lastSeenPi), baseURL: nil)
    case .nous:
      window.subtitle = "連不到"
      let html = """
      <!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
      <style>:root{color-scheme:light dark}body{font:15px -apple-system,"PingFang TC",sans-serif;margin:40px;line-height:1.6}code{font:13px ui-monospace,Menlo,monospace}</style>
      <h1 style="font-size:20px">連不到鴨子用的 Nous（\(nousPort)）</h1><p>\(htmlEscape(ns.localizedDescription))</p>
      <p>它由 LaunchAgent <code>\(nousAgent)</code> 常駐。剛重新啟動時要等十幾秒（啟動時會先建置頁面）；一直連不到就看選單列的「打開 log 資料夾」裡的 <code>nous.log</code>。</p>
      <p><a href="duckmenu://retry">重試</a></p>
      """
      webView.loadHTMLString(html, baseURL: nil)
    }
  }

  /// 驗證用：--snapshot <路徑.png> 時，頁面載完 3 秒後把視窗內容存成 PNG 就結束（不需要螢幕權限）。
  private var snapshotDone = false
  private func snapshotIfRequested() {
    guard !snapshotDone, let i = CommandLine.arguments.firstIndex(of: "--snapshot"), i + 1 < CommandLine.arguments.count else { return }
    snapshotDone = true
    let path = CommandLine.arguments[i + 1]
    DispatchQueue.main.asyncAfter(deadline: .now() + (self.kind == .nous ? 9 : 3)) {
      self.webView.takeSnapshot(with: nil) { image, error in
        if let image, let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
          try? png.write(to: URL(fileURLWithPath: path))
          print("snapshot: \(path) subtitle=\(self.window.subtitle)")
        } else {
          print("snapshot failed: \(error?.localizedDescription ?? "?")")
        }
        exit(0)
      }
    }
  }

  func windowWillClose(_ notification: Notification) {
    // 關掉視窗就停掉頁面（8791 的頁面有心跳與事件串流，不讓它在背景一直開著）。
    webView.loadHTMLString("", baseURL: nil)
  }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
  var statusItem: NSStatusItem!
  let menu = NSMenu()
  var snapshot = Snapshot()
  var refreshing = false
  var lastSeenPi: Date?
  var timer: Timer?
  lazy var nousWindow = WebWindow(kind: .nous)
  lazy var duckWindow = WebWindow(kind: .duck)

  func applicationDidFinishLaunching(_ notification: Notification) {
    installEditMenu()
    statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    setIcon(connected: false)
    menu.delegate = self
    menu.autoenablesItems = false
    statusItem.menu = menu
    rebuildMenu()
    refresh()
    timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in self?.refresh() }
    // 開發與驗證用：--open nous／--open duck 啟動時直接開那個視窗。
    if let i = CommandLine.arguments.firstIndex(of: "--open"), i + 1 < CommandLine.arguments.count {
      switch CommandLine.arguments[i + 1] {
      case "nous": nousWindow.show()
      case "duck": duckWindow.show()
      default: break
      }
    }
  }

  /// 選單列 App 沒有主選單；沒有「編輯」選單的話，網頁裡的輸入欄不能用 ⌘C／⌘V。
  func installEditMenu() {
    let main = NSMenu()
    let editItem = NSMenuItem()
    let edit = NSMenu(title: "編輯")
    edit.addItem(withTitle: "還原", action: Selector(("undo:")), keyEquivalent: "z")
    edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
    edit.addItem(.separator())
    edit.addItem(withTitle: "剪下", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    edit.addItem(withTitle: "拷貝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    edit.addItem(withTitle: "貼上", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    edit.addItem(withTitle: "全選", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
    edit.addItem(.separator())
    edit.addItem(withTitle: "關閉視窗", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
    edit.addItem(withTitle: "重新載入", action: #selector(WKWebView.reload(_:)), keyEquivalent: "r")
    editItem.submenu = edit
    main.addItem(editItem)
    NSApp.mainMenu = main
  }

  func setIcon(connected: Bool) {
    guard let button = statusItem.button else { return }
    let name = connected ? "bird.fill" : "bird"
    if let image = NSImage(systemSymbolName: name, accessibilityDescription: "鴨子 Nous") {
      image.isTemplate = true
      button.image = image
      button.title = ""
    } else {
      button.title = connected ? "🦆" : "🦆?"
    }
    button.toolTip = connected ? "鴨子 Nous：鴨子已連線" : "鴨子 Nous：鴨子沒有連線"
  }

  func refresh() {
    guard !refreshing else { return }
    refreshing = true
    let host = piHost
    DispatchQueue.global(qos: .userInitiated).async {
      let s = collect(host: host)
      DispatchQueue.main.async {
        self.refreshing = false
        self.snapshot = s
        if s.piReachable == true { self.lastSeenPi = Date(); self.duckWindow.lastSeenPi = self.lastSeenPi }
        let duck = duckLinkLine(s.nous.integrations)
        self.setIcon(connected: duck?.level == .ok)
        self.rebuildMenu()
      }
    }
  }

  func menuWillOpen(_ menu: NSMenu) { refresh() }

  private func statusItem(_ line: Line) -> NSMenuItem {
    let item = NSMenuItem(title: line.menuTitle, action: nil, keyEquivalent: "")
    item.isEnabled = false
    if let note = line.note {
      item.toolTip = note
      if #available(macOS 14.4, *) { item.subtitle = note }
    }
    return item
  }

  private func action(_ title: String, _ selector: Selector, enabled: Bool = true, note: String? = nil) -> NSMenuItem {
    let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
    item.target = self
    item.isEnabled = enabled
    if let note {
      item.toolTip = note
      if #available(macOS 14.4, *) { item.subtitle = note }
    }
    return item
  }

  func rebuildMenu() {
    menu.removeAllItems()
    let s = snapshot
    let header = NSMenuItem(title: "鴨子 Nous（\(nousPort)）", action: nil, keyEquivalent: "")
    header.isEnabled = false
    menu.addItem(header)
    menu.addItem(statusItem(nousLine(agent: s.nousAgentState, snapshot: s.nous, port: nousPort)))
    for line in [engineLine(s.nous.settings), chatgptLine(s.nous.settings), realtimeLine(s.nous.settings), duckLinkLine(s.nous.integrations)].compactMap({ $0 }) {
      menu.addItem(statusItem(line))
    }
    menu.addItem(statusItem(tunnelLine(agent: s.tunnelAgentState, tunnelLogTail: s.tunnelLogTail, duckConnected: duckLinkLine(s.nous.integrations)?.level == .ok)))
    menu.addItem(statusItem(piLine(host: piHost, reachable: s.piReachable, lastSeen: lastSeenPi)))

    menu.addItem(.separator())
    let nousUp = s.nous.settings != nil
    menu.addItem(action("Nous 設定…", #selector(openNousSettings), enabled: nousUp, note: nousUp ? "引擎、ChatGPT 與即時語音登入、語音秒數（8791 的設定畫面）" : "Nous（\(nousPort)）沒有回應"))
    let piUp = s.piReachable == true
    menu.addItem(action("鴨子設定…", #selector(openDuckSettings), enabled: piUp, note: piUp ? "喚醒詞與門檻、喇叭音量、聽聲轉頭、表情（Pi 上的設定頁）" : "連不到鴨子：Pi 可能關機或不在同一個 Wi-Fi"))
    menu.addItem(action("鴨子的位址：\(piHost)…", #selector(editPiHost)))

    menu.addItem(.separator())
    menu.addItem(action("在瀏覽器打開 Nous（\(nousPort)）", #selector(openInBrowser), enabled: nousUp))
    menu.addItem(action("打開 log 資料夾", #selector(openLogs)))
    menu.addItem(action("重新啟動 Nous…", #selector(restartNous), enabled: s.nousAgentState != .notLoaded, note: "會中斷鴨子正在進行的對話"))
    menu.addItem(.separator())
    menu.addItem(action("重新整理狀態", #selector(refreshNow)))
    let quit = NSMenuItem(title: "結束鴨子 Nous", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    quit.toolTip = "只關掉這個選單列圖示；Nous 與通道照常在跑"
    menu.addItem(quit)
  }

  @objc func openNousSettings() { nousWindow.show() }
  @objc func openDuckSettings() { duckWindow.show() }
  @objc func refreshNow() { refresh() }
  @objc func openInBrowser() { NSWorkspace.shared.open(URL(string: "http://localhost:\(nousPort)/")!) }
  @objc func openLogs() { NSWorkspace.shared.open(logDir) }

  @objc func editPiHost() {
    let alert = NSAlert()
    alert.messageText = "鴨子（Pi）的位址"
    alert.informativeText = "主機名稱或 IP，例如 duck-pi4.local。只存在這台 Mac（不進 repo）。留空＝回到預設 \(defaultPiHost)。"
    let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24))
    field.stringValue = piHost
    alert.accessoryView = field
    alert.addButton(withTitle: "儲存")
    alert.addButton(withTitle: "取消")
    NSApp.activate(ignoringOtherApps: true)
    guard alert.runModal() == .alertFirstButtonReturn else { return }
    let text = field.stringValue.trimmingCharacters(in: .whitespaces)
    if text.isEmpty {
      UserDefaults.standard.removeObject(forKey: "piHost")
    } else if let host = normalizedPiHost(text) {
      piHost = host
    } else {
      let bad = NSAlert()
      bad.messageText = "這不是主機名稱或 IP：\(text)"
      bad.informativeText = "只能有英文字母、數字、點與減號（不要加 http:// 或埠號）。"
      bad.runModal()
      return
    }
    lastSeenPi = nil
    refresh()
  }

  @objc func restartNous() {
    let alert = NSAlert()
    alert.messageText = "重新啟動鴨子用的 Nous（\(nousPort)）？"
    alert.informativeText = "鴨子正在進行的對話會中斷，鴨子會斷線後自動重連。啟動要十幾秒（會先建置頁面）。平常用的 Nous（8787）不受影響。"
    alert.addButton(withTitle: "重新啟動")
    alert.addButton(withTitle: "取消")
    NSApp.activate(ignoringOtherApps: true)
    guard alert.runModal() == .alertFirstButtonReturn else { return }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
    p.arguments = ["kickstart", "-k", "gui/\(getuid())/\(nousAgent)"]
    p.terminationHandler = { proc in
      DispatchQueue.main.async {
        if proc.terminationStatus != 0 {
          let fail = NSAlert()
          fail.messageText = "沒有重新啟動（launchctl 回 \(proc.terminationStatus)）"
          fail.runModal()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { self.refresh() }
      }
    }
    do { try p.run() } catch {
      let fail = NSAlert()
      fail.messageText = "沒有重新啟動：\(error.localizedDescription)"
      fail.runModal()
    }
    refresh()
  }
}

// --status：不開選單列，只印出目前狀態（給安裝腳本與驗證用）。
if CommandLine.arguments.contains("--status") {
  let s = collect(host: piHost)
  let lines = [nousLine(agent: s.nousAgentState, snapshot: s.nous, port: nousPort)]
    + [engineLine(s.nous.settings), chatgptLine(s.nous.settings), realtimeLine(s.nous.settings), duckLinkLine(s.nous.integrations)].compactMap { $0 }
    + [tunnelLine(agent: s.tunnelAgentState, tunnelLogTail: s.tunnelLogTail, duckConnected: duckLinkLine(s.nous.integrations)?.level == .ok), piLine(host: piHost, reachable: s.piReachable, lastSeen: nil)]
  for line in lines { print(line.menuTitle + (line.note.map { "　— \($0)" } ?? "")) }
  exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
