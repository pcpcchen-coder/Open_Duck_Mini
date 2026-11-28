// 鴨子 Nous 選單列：把各來源的原始資料變成選單上的一行字（純函式，不碰網路與 AppKit；SelfTest.swift 直接測）。
//
// 來源：
//   Nous（8791）的 GET /api/settings、GET /api/integrations/status
//   launchctl print gui/<uid>/<label> 的輸出（com.nousduck.nous-dev、com.nousduck.duck-tunnel）
//   Pi 設定頁的 GET /healthz（回 "ok"）
// 規則：只說看得到的事；沒拿到資料就說「不知道」，不推定正常。不顯示帳號 email 或任何秘密。

import Foundation

enum Level: String {
  case ok, warn, bad, unknown
}

struct Line: Equatable {
  let level: Level
  let text: String
  /// 灰色的第二行（選單的 toolTip／說明）；沒有就 nil。
  let note: String?

  init(_ level: Level, _ text: String, note: String? = nil) {
    self.level = level
    self.text = text
    self.note = note
  }

  /// 選單上看到的樣子：前面一個狀態符號。
  var menuTitle: String {
    let mark: String
    switch level {
    case .ok: mark = "●"
    case .warn: mark = "◐"
    case .bad: mark = "○"
    case .unknown: mark = "?"
    }
    return "\(mark) \(text)"
  }
}

// MARK: - launchd

enum AgentState: Equatable {
  case running(pid: Int?)
  case loadedNotRunning
  case notLoaded
}

/// 解析 `launchctl print gui/<uid>/<label>` 的輸出；exitCode 非 0 代表沒有載入。
func parseLaunchctl(output: String, exitCode: Int32) -> AgentState {
  if exitCode != 0 { return .notLoaded }
  var state: String?
  var pid: Int?
  for raw in output.components(separatedBy: .newlines) {
    // 只看第一層（一個 tab 縮排）的欄位；更深的是 endpoint 之類，不算服務狀態。
    guard raw.hasPrefix("\t"), !raw.hasPrefix("\t\t") else { continue }
    let line = raw.trimmingCharacters(in: .whitespaces)
    if line.hasPrefix("state = ") { state = String(line.dropFirst("state = ".count)) }
    if line.hasPrefix("pid = ") { pid = Int(line.dropFirst("pid = ".count)) }
  }
  return state == "running" ? .running(pid: pid) : .loadedNotRunning
}

// MARK: - Nous（8791）

struct NousSnapshot {
  /// GET /api/settings 的 JSON；nil＝沒拿到。
  var settings: [String: Any]?
  /// GET /api/integrations/status 的 JSON；nil＝沒拿到。
  var integrations: [String: Any]?
  /// 連線失敗的原因（給人看）；拿到資料時是 nil。
  var error: String?
}

func jsonObject(_ data: Data?) -> [String: Any]? {
  guard let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
  return obj
}

/// 「Nous（8791）」那一行：LaunchAgent＋HTTP 合起來看。
func nousLine(agent: AgentState, snapshot: NousSnapshot, port: Int) -> Line {
  if snapshot.settings != nil {
    switch agent {
    case .running(let pid): return Line(.ok, "Nous（\(port)）在跑", note: pid.map { "LaunchAgent com.nousduck.nous-dev，pid \($0)" })
    default: return Line(.ok, "Nous（\(port)）在跑", note: "不是由 LaunchAgent 啟動的（手動開的？）")
    }
  }
  switch agent {
  case .running: return Line(.warn, "Nous（\(port)）啟動中或沒有回應", note: snapshot.error)
  case .loadedNotRunning: return Line(.bad, "Nous（\(port)）沒有在跑", note: "LaunchAgent 已載入但沒有行程；看 log")
  case .notLoaded: return Line(.bad, "Nous（\(port)）沒有在跑", note: "LaunchAgent com.nousduck.nous-dev 沒有載入（bash nous_duck/tools/mac_launch_agents.sh）")
  }
}

/// AI 引擎那一行。settings 是 /api/settings。
func engineLine(_ settings: [String: Any]?) -> Line? {
  guard let settings else { return nil }
  let provider = settings["provider"] as? String ?? "?"
  let providers = settings["providers"] as? [[String: Any]] ?? []
  let current = providers.first { ($0["id"] as? String) == provider }
  let label = current?["label"] as? String ?? provider
  let available = current?["available"] as? Bool ?? false
  if provider == "mock" { return Line(.warn, "AI 引擎：\(label)", note: "不呼叫任何模型，只展示流程") }
  return available ? Line(.ok, "AI 引擎：\(label)") : Line(.bad, "AI 引擎：\(label)（不可用）", note: current?["detail"] as? String)
}

/// ChatGPT 登入那一行。只說有沒有登入，不顯示帳號。
func chatgptLine(_ settings: [String: Any]?) -> Line? {
  guard let chatgpt = settings?["chatgpt"] as? [String: Any] else { return nil }
  if chatgpt["pending_login"] as? Bool == true { return Line(.warn, "ChatGPT：登入中…") }
  if chatgpt["needs_reauth"] as? Bool == true { return Line(.bad, "ChatGPT：要重新登入", note: "在「Nous 設定…」裡登入") }
  if chatgpt["signed_in"] as? Bool == true { return Line(.ok, "ChatGPT：已登入") }
  return Line(.bad, "ChatGPT：沒有登入", note: "在「Nous 設定…」裡登入")
}

/// 即時語音那一行（鴨子對話走這條）。
func realtimeLine(_ settings: [String: Any]?) -> Line? {
  guard let realtime = settings?["realtime"] as? [String: Any] else { return nil }
  let billing = realtime["billing_line"] as? String
  if realtime["available"] as? Bool == true {
    let active = realtime["active"]
    let inCall = active != nil && !(active is NSNull)
    return Line(.ok, "即時語音：可用\(inCall ? "（對話中）" : "")", note: billing)
  }
  return Line(.bad, "即時語音：不可用", note: (realtime["detail"] as? String) ?? "在「Nous 設定…」→ 即時語音登入")
}

/// 鴨子（duck-link）那一行。integrations 是 /api/integrations/status。
func duckLinkLine(_ integrations: [String: Any]?) -> Line? {
  guard let integrations else { return nil }
  let services = integrations["services"] as? [[String: Any]] ?? []
  guard let duck = services.first(where: { ($0["service"] as? String) == "duck" }) else {
    return Line(.bad, "鴨子：Nous 沒有開鴨子功能", note: "要 NOUS_DUCK=on、NOUS_AIL=on、NOUS_AIL_SERVICES=duck")
  }
  let mock = duck["mock"] as? Bool == true
  let tag = mock ? "（mock）" : ""
  let health = duck["health"] as? String ?? "unknown"
  let reason = duck["reason"] as? String
  switch health {
  case "available": return Line(mock ? .warn : .ok, "鴨子：已連線\(tag)", note: mock ? "連著的是模擬身體，不是真的鴨子" : nil)
  case "unavailable":
    let why: String
    switch reason {
    case "unreachable": why = "從這次啟動後還沒連上過"
    case "connection_closed": why = "連線斷了（Pi 關機、通道斷了，或 duckd 沒在跑）"
    default: why = reason ?? "沒有說原因"
    }
    return Line(.bad, "鴨子：沒有連線\(tag)", note: why)
  default: return Line(.warn, "鴨子：連著但還沒有狀態\(tag)", note: reason == "not_ready" ? "duckd 還沒送狀態，或狀態太舊" : reason)
  }
}

/// 通道那一行。tunnelLogTail 是 tunnel.log 最後幾行（找不到主機之類的錯誤會在這裡）。
/// ssh 行程在跑不等於連上了（Pi 關機時 ssh 會一直重試）：只有鴨子真的連上 duck-link 才說「連著」。
func tunnelLine(agent: AgentState, tunnelLogTail: String?, duckConnected: Bool) -> Line {
  // ssh 的錯誤訊息是 \r\n 結尾；Swift 把 \r\n 當成一個字元，所以用 newlines 切。
  let lastError = tunnelLogTail?
    .components(separatedBy: .newlines)
    .last { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
  switch agent {
  case .running where duckConnected: return Line(.ok, "通道（SSH 到鴨子）：連著", note: "com.nousduck.duck-tunnel")
  case .running: return Line(.warn, "通道（SSH 到鴨子）：ssh 在跑，鴨子還沒連上", note: lastError)
  case .loadedNotRunning: return Line(.bad, "通道（SSH 到鴨子）：沒連上，會自動重試", note: lastError)
  case .notLoaded: return Line(.bad, "通道（SSH 到鴨子）：沒有裝", note: "LaunchAgent com.nousduck.duck-tunnel 沒有載入")
  }
}

/// Pi 設定頁那一行。
func piLine(host: String, reachable: Bool?, lastSeen: Date?, now: Date = Date()) -> Line {
  switch reachable {
  case .some(true): return Line(.ok, "鴨子設定頁：連得到（\(host)）")
  case .some(false):
    return Line(.bad, "鴨子設定頁：連不到（\(host)）", note: "Pi 可能關機或不在同一個 Wi-Fi" + (lastSeen.map { "；上次連到：\(relativeTime($0, now: now))" } ?? ""))
  case .none: return Line(.unknown, "鴨子設定頁：檢查中（\(host)）")
  }
}

func relativeTime(_ date: Date, now: Date = Date()) -> String {
  let s = Int(now.timeIntervalSince(date))
  if s < 60 { return "剛剛" }
  if s < 3600 { return "\(s / 60) 分鐘前" }
  if s < 86400 { return "\(s / 3600) 小時前" }
  let f = DateFormatter()
  f.dateFormat = "M/d HH:mm"
  return f.string(from: date)
}

// MARK: - 主機名稱

/// 使用者自己填的 Pi 位址：只接受主機名稱或 IP（不含協定、路徑、埠以外的東西）。
func normalizedPiHost(_ input: String) -> String? {
  let s = input.trimmingCharacters(in: .whitespacesAndNewlines)
  guard !s.isEmpty, s.count <= 253 else { return nil }
  let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
  guard s.unicodeScalars.allSatisfy({ allowed.contains($0) }), !s.hasPrefix("."), !s.hasPrefix("-") else { return nil }
  return s.lowercased()
}

// MARK: - 離線頁

func htmlEscape(_ s: String) -> String {
  s.replacingOccurrences(of: "&", with: "&amp;")
    .replacingOccurrences(of: "<", with: "&lt;")
    .replacingOccurrences(of: ">", with: "&gt;")
    .replacingOccurrences(of: "\"", with: "&quot;")
}

/// 連不到 Pi 時視窗裡顯示的頁面（本機產生，不連網）。按「重試」導到 duckmenu://retry，由 App 攔下來。
func offlinePageHTML(host: String, port: Int, reason: String, lastSeen: Date?, now: Date = Date()) -> String {
  let seen = lastSeen.map { "上次連到：\(relativeTime($0, now: now))" } ?? "這台 Mac 開著這個 App 之後還沒有連到過"
  return """
  <!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
  <style>
  :root { color-scheme: light dark; }
  body { font: 15px -apple-system, "PingFang TC", sans-serif; margin: 40px; line-height: 1.6; }
  h1 { font-size: 20px; } code { font: 13px ui-monospace, Menlo, monospace; }
  .muted { opacity: .7; } a.btn { display: inline-block; padding: 6px 16px; border-radius: 6px; background: #0a64d8; color: #fff; text-decoration: none; }
  li { margin: 4px 0; }
  </style></head><body>
  <h1>連不到鴨子的設定頁</h1>
  <p>位址 <code>http://\(htmlEscape(host)):\(port)/</code>：\(htmlEscape(reason))</p>
  <p class="muted">\(htmlEscape(seen))</p>
  <p>常見原因：</p>
  <ul>
  <li>鴨子（Pi）關機，或還在開機（開機後大約一分鐘設定頁才會起來）。</li>
  <li>Mac 和鴨子不在同一個 Wi-Fi。</li>
  <li>這台 Mac 認不得 <code>.local</code> 名稱：在選單列「鴨子的位址…」改成 Pi 的 IP。</li>
  <li>第一次使用時 macOS 會問「允許尋找區域網路上的裝置」，要按允許（系統設定 → 隱私權與安全性 → 區域網路）。</li>
  </ul>
  <p><a class="btn" href="duckmenu://retry">重試</a></p>
  </body></html>
  """
}
