# Security and privacy

- Treat Telegram session strings as account credentials. Never send them, bot tokens, API hashes, or encryption keys in chat or commit them to Git.
- Restrict onboarding with `ALLOWED_USER_IDS` and/or `GOD_ADMIN_IDS`. Do not expose this as an unrestricted public login service.
- Set `SESSION_ENCRYPTION_KEY` to a Fernet key generated offline using:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  Store the result in your deployment secret settings, not in this repository. Keep a secure backup of the key; losing it makes encrypted sessions unusable. Do not regenerate it on each deployment.
- Back up the persistent volume before upgrading. Existing plaintext databases and their backups may contain active sessions even after migration. Protect old backups and revoke compromised Telegram sessions through Telegram Settings > Devices.
- Disconnecting a client is not the same as revoking its Telegram authorization. Use Telegram's device management to revoke authorization.
- AI sends selected prompts, reply text, and relevant history to the configured HTTPS provider. TTS sends text to Microsoft Edge TTS. Automatic translation sends text to Google's translation endpoint. Enable these features only for text you are authorized to share.
- Archive features may retain messages other people deleted or intended to expire. Respect consent and applicable rules. Clearing local cache cannot delete copies already sent to Saved Messages or external backups.
- Telegram may impose rate limits or restrict accounts using automation. Tests cannot guarantee future server behavior or immunity from restrictions.
- Run one service instance against one SQLite volume. Multiple replicas are not supported by this release.
- Keep the persistent data directory private. Do not serve it through a web server, publish it as an artifact, or include it in source ZIPs.
- If a token was pasted into chat, revoke it at the issuer. Removing a message does not make a previously disclosed credential safe again.
