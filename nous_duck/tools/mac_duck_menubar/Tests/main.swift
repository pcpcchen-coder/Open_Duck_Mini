// Status.swift 的自我測試（不連網、不碰 AppKit）。執行：bash build.sh --test
// 這裡的 JSON 全部是手寫的 fixture（形狀照 AIOS main 607db1d 的 /api/settings、/api/integrations/status），不是實際資料；
// 帳號一律用假的 fixture@example.invalid，用來確認選單不會把它顯示出來。

import Foundation

var failures = 0
var count = 0
func check(_ cond: Bool, _ name: String, file: StaticString = #file, line: UInt = #line) {
  count += 1
  if !cond { failures += 1; print("✗ \(name)（第 \(line) 行）") }
}
func obj(_ s: String) -> [String: Any] { jsonObject(s.data(using: .utf8))! }

// launchctl
let running = "gui/501/com.nousduck.nous-dev = {\n\tactive count = 1\n\tstate = running\n\tpid = 56695\n\tendpoints = {\n\t\tstate = active\n\t}\n}\n"
check(parseLaunchctl(output: running, exitCode: 0) == .running(pid: 56695), "launchctl：running＋pid")
let waiting = "gui/501/x = {\n\tstate = not running\n\tlast exit code = 255\n}\n"
check(parseLaunchctl(output: waiting, exitCode: 0) == .loadedNotRunning, "launchctl：載入但沒在跑")
check(parseLaunchctl(output: "", exitCode: 113) == .notLoaded, "launchctl：沒有載入")
check(parseLaunchctl(output: "\t\tstate = running\n", exitCode: 0) == .loadedNotRunning, "launchctl：深層的 state 不算")

// Nous 這一行
let settings = obj("""
{"provider":"chatgpt","providers":[{"id":"claude","label":"Claude","available":false,"detail":"未設定 ANTHROPIC_API_KEY"},{"id":"chatgpt","label":"ChatGPT","available":true,"detail":"使用 fixture@example.invalid 的 ChatGPT 方案"},{"id":"mock","label":"模擬","available":true}],
 "chatgpt":{"signed_in":true,"email":"fixture@example.invalid","needs_reauth":false,"pending_login":false},
 "realtime":{"available":true,"billing_line":"ChatGPT 方案（Codex 額度）· gpt-live-1-codex","active":null,"detail":"…"}}
""")
let up = NousSnapshot(settings: settings, integrations: nil, error: nil)
check(nousLine(agent: .running(pid: 1), snapshot: up, port: 8791).level == .ok, "Nous：有回應＝在跑")
check(nousLine(agent: .notLoaded, snapshot: up, port: 8791).note?.contains("不是由 LaunchAgent") == true, "Nous：手動開的照實說")
let down = NousSnapshot(settings: nil, integrations: nil, error: "Could not connect")
check(nousLine(agent: .running(pid: 1), snapshot: down, port: 8791).level == .warn, "Nous：行程在但沒回應＝啟動中")
check(nousLine(agent: .notLoaded, snapshot: down, port: 8791).level == .bad, "Nous：沒有在跑")

// 引擎、登入、即時語音
check(engineLine(settings)?.text == "AI 引擎：ChatGPT", "引擎：ChatGPT")
check(engineLine(nil) == nil, "引擎：沒資料不顯示")
var mockSettings = settings; mockSettings["provider"] = "mock"
check(engineLine(mockSettings)?.level == .warn, "引擎：模擬要標出來")
var claude = settings; claude["provider"] = "claude"
check(engineLine(claude)?.level == .bad, "引擎：選了不可用的引擎")
check(chatgptLine(settings)?.text == "ChatGPT：已登入", "ChatGPT：已登入")
let allText = [engineLine(settings), chatgptLine(settings), realtimeLine(settings)].compactMap { $0 }.map { $0.text + ($0.note ?? "") }.joined()
check(!allText.contains("@"), "不顯示帳號 email")
check(chatgptLine(obj(#"{"chatgpt":{"signed_in":false}}"#))?.level == .bad, "ChatGPT：沒登入")
check(chatgptLine(obj(#"{"chatgpt":{"signed_in":true,"needs_reauth":true}}"#))?.text == "ChatGPT：要重新登入", "ChatGPT：要重新登入")
check(realtimeLine(settings)?.text == "即時語音：可用", "即時語音：可用")
check(realtimeLine(obj(#"{"realtime":{"available":true,"active":{"id":"x"}}}"#))?.text == "即時語音：可用（對話中）", "即時語音：對話中")
check(realtimeLine(obj(#"{"realtime":{"available":false,"detail":"未登入"}}"#))?.note == "未登入", "即時語音：不可用附原因")

// 鴨子
let closed = obj(#"{"services":[{"service":"duck","mock":false,"health":"unavailable","reason":"connection_closed"}]}"#)
check(duckLinkLine(closed)?.text == "鴨子：沒有連線", "鴨子：斷線")
check(duckLinkLine(closed)?.note?.contains("Pi 關機") == true, "鴨子：斷線原因")
let ok = obj(#"{"services":[{"service":"duck","mock":false,"health":"available","reason":"ok"}]}"#)
check(duckLinkLine(ok)?.level == .ok, "鴨子：已連線")
let mockDuck = obj(#"{"services":[{"service":"duck","mock":true,"health":"available","reason":"ok"}]}"#)
check(duckLinkLine(mockDuck)?.level == .warn && duckLinkLine(mockDuck)?.text.contains("mock") == true, "鴨子：mock 要標出來、不算綠燈")
check(duckLinkLine(obj(#"{"services":[]}"#))?.text == "鴨子：Nous 沒有開鴨子功能", "鴨子：旗標沒開")
check(duckLinkLine(obj(#"{"services":[{"service":"duck","health":"unknown","reason":"not_ready"}]}"#))?.level == .warn, "鴨子：還沒有狀態")
check(duckLinkLine(nil) == nil, "鴨子：沒資料不顯示")

// 通道
let log = "ssh: connect to host x port 22: Operation timed out\nssh: Could not resolve hostname duck-pi4.local: nodename nor servname provided, or not known\n"
check(tunnelLine(agent: .running(pid: 2), tunnelLogTail: log, duckConnected: true).level == .ok, "通道：鴨子連上＝連著")
check(tunnelLine(agent: .running(pid: 2), tunnelLogTail: log, duckConnected: false).level == .warn, "通道：ssh 在跑但鴨子沒連上不說連著")
check(tunnelLine(agent: .loadedNotRunning, tunnelLogTail: log, duckConnected: false).note?.contains("Could not resolve") == true, "通道：附最後一行錯誤")
let crlf = "ssh: a\r\nssh: Could not resolve hostname duck-pi4.local\r\n"
check(tunnelLine(agent: .loadedNotRunning, tunnelLogTail: crlf, duckConnected: false).note == "ssh: Could not resolve hostname duck-pi4.local", "通道：\\r\\n 結尾只取最後一行")
check(tunnelLine(agent: .notLoaded, tunnelLogTail: nil, duckConnected: false).text.contains("沒有裝"), "通道：沒裝")

// Pi 設定頁
let now = Date(timeIntervalSince1970: 1_800_000_000)
check(piLine(host: "duck-pi4.local", reachable: true, lastSeen: nil).level == .ok, "Pi：連得到")
check(piLine(host: "duck-pi4.local", reachable: false, lastSeen: now.addingTimeInterval(-300), now: now).note?.contains("5 分鐘前") == true, "Pi：連不到附上次時間")
check(piLine(host: "duck-pi4.local", reachable: nil, lastSeen: nil).level == .unknown, "Pi：還沒查完不猜")

// 主機名稱
check(normalizedPiHost(" Duck-Pi4.local ") == "duck-pi4.local", "位址：去空白、小寫")
check(normalizedPiHost("192.168.0.10") == "192.168.0.10", "位址：IP")
check(normalizedPiHost("http://duck-pi4.local") == nil, "位址：不收協定")
check(normalizedPiHost("duck-pi4.local:8081") == nil, "位址：不收埠號")
check(normalizedPiHost("a b") == nil, "位址：不收空白")
check(normalizedPiHost("") == nil, "位址：空的")

// 離線頁
let page = offlinePageHTML(host: "<x>", port: 8081, reason: "\"bad\"", lastSeen: nil, now: now)
check(page.contains("&lt;x&gt;") && !page.contains("<x>"), "離線頁：主機名稱跳脫")
check(page.contains("&quot;bad&quot;"), "離線頁：原因跳脫")
check(page.contains("duckmenu://retry"), "離線頁：有重試")
check(page.contains("default-src 'none'"), "離線頁：不載入任何外部資源")

print(failures == 0 ? "全部通過：\(count) 項" : "失敗 \(failures)／\(count) 項")
exit(failures == 0 ? 0 : 1)
