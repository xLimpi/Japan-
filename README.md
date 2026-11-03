# Zu Fuss durch Japan

Friends' page for three walks: Nakasendō (2024), Tōkaidō (2024) and San'yōdō (2026).
The page and its photos are encrypted; you need the password to open it.

It's built from the planner on claude.ai, not edited here:

1. Save the published planner page and the collections `public`, `tracks`, `j1tracks`, `j3tracks`, `weather`, `j1weather` and `j3weather` from its database, as `DATA/<collection>/<doc>.json`.
2. Download any photo listed in a `public/*` document that has no `img/<asset>.bin` yet, as `ASSETS/<asset>.jpg`.
3. Run `python3 tools/build_site.py --page PAGE.html --data DATA --assets ASSETS --out . --password PW`, then commit and push.
