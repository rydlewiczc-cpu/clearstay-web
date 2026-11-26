# Clearstay Web & Anonymous Static Live Briefings Feed (`$0/mo`)

Public static site and zero-tracking global briefings feed for **Clearstay iOS**:

- **Landing Page:** `https://rydlewiczc-cpu.github.io/clearstay-web/`
- **App Store Privacy Policy:** `https://rydlewiczc-cpu.github.io/clearstay-web/privacy.html`
- **App Store Support Page:** `https://rydlewiczc-cpu.github.io/clearstay-web/support.html`
- **Live Briefings Static Feed:** `https://rydlewiczc-cpu.github.io/clearstay-web/snapshot-v1.json`

## Pushing an Emergency Broadcast (from iPhone or Desktop)
1. Open **Actions → Broadcast Emergency Alert → Run workflow** in this repo.
2. Pick `publish`, enter Headline, Severity, Country ISO-3 codes (or blank for Global), and Summary, then click **Run workflow**.
3. Your custom alert goes live inside `snapshot-v1.json` in ~30 seconds. Use `clear_all` anytime to clear active custom alerts.
