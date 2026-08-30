# 2. Threat Model

[← Security Architecture and Threat Model](../security.md)

| Source | Scenario | Impact | Section |
|---|---|---|---|
| Public attacker | Scans the gateway, brute-forces keys, exploits unpatched CVEs | Resource abuse, possible execution | §4, §10 |
| Public attacker | **Forges `Tailscale-*` headers against the public admin entrance** | **Full admin access** | §5.1 |
| Public attacker | Brute-force or credential-stuffs the admin login | Full admin access if a password is reused or weak | §5.3 |
| Public attacker | Probes login responses to enumerate accounts | Target list for phishing | §5.3 |
| Public attacker | Replays an observed TOTP code within its window | Second factor defeated | §5.3 |
| Interception | An invitation or reset link is delivered over an insecure channel | Account takeover before the intended user acts | §5.4 |
| Same-LAN device | Guest wifi or compromised IoT reaches an accidentally published database port | Direct database read | §3.3 |
| Tailnet member | Stolen laptop or account; a `user` attempting admin functions | Up to full control | §5 |
| Tailnet member | Connects directly to `100.x.x.x:8000` and bypasses the proxy | Skips proxy-side controls | §3.4 |
| Malicious model file | Downloaded weights contain a malicious pickle payload | Host code execution | §7.1 |
| Model name injection | Model reference concatenated into a shell command | Host code execution | §7.1 |
| SSRF | Node registration address points at an internal service | Internal probing | §7.2 |
| Prompt injection | Knowledge base documents carry embedded instructions | Data disclosure, manipulated output | §7.3 |
| Supply chain | Poisoned pip, npm, or Docker dependency | Full compromise | §10 |
| Physical access | Someone reaches the Mac Studio itself | Disk contents, credentials | §11 |
| Own mistakes | Key committed to git, collection deleted | Disclosure, data loss | §8, §12 |
| Resource exhaustion | One leaked key drives inference around the clock | Service unavailable, thermal throttling | §4.3 |
