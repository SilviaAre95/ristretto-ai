---
type: project
status: active
tags: [project/ristretto-ai, system/dev]
created: 2026-07-02
updated: 2026-07-02
summary: "Readable guide to the generic Ristretto Slack app manifest."
---

# Ristretto AI — Slack App Manifest

The uploadable manifest lives at `slack/ristretto-slack-manifest.json`.

## How to use
1. Go to <https://api.slack.com/apps> → **Create New App** → **From an app manifest**.
2. Pick a personal workspace.
3. Paste the JSON below (or upload `hermes-slack-manifest.json`).
4. Store tokens and `SLACK_ALLOWED_USERS` only in `~/.hermes/.env`, then invite the bot to the configured channels.

## Manifest

```json
{
  "display_information": {
    "name": "Ristretto Ops",
    "description": "Ristretto AI — personal ops assistant (Hermes Agent gateway)",
    "background_color": "#1a1d29"
  },
  "features": {
    "bot_user": {
      "display_name": "RistrettoOps",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "chat:write",
        "channels:history",
        "groups:history",
        "im:history",
        "files:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "app_mention",
        "message.channels",
        "message.groups",
        "message.im"
      ]
    },
    "interactivity": {
      "is_enabled": true
    },
    "socket_mode_enabled": true,
    "org_deploy_enabled": false,
    "token_rotation_enabled": false
  }
}
```

## Related
- [[README]]
