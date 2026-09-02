# 6706 Transactions API

Static JSON API for transaction records assigned to affiliate ID `6706`.

The project syncs the following Google Sheet fields: transaction ID, offer ID,
affiliate ID, datetime, status, payout, revenue, sale amount, affiliate tracking
info, GEO, sales status, and month.

Run the sync locally:

```bash
python3 scripts/sync_sheet.py
```

The generated endpoint is:

```text
docs/api/transactions.json
```

For GitHub Pages, enable Pages from the `docs/` folder on the `main` branch.
The GitHub Action runs every 15 minutes and commits changed JSON data.
