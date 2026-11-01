# ALTA signals

Reproducible numbers behind the "What could be seen in the reports" section of the
public analysis: https://claude.ai/artifact/RrfqFLbzQh5wEkb9RxC7UQ

- `signals.csv` - every figure of that section: signal number, bank, metric, period,
  value, unit, formula and source.
- `signals.py` - recomputes the CSV from the sources. Standard library only, Python 3.10+.

## Data sources

- Public CSV reports of the National Bank of Serbia (balance sheets and income
  statements of all 19 banks): https://webappcenter.nbs.rs/WebApp/FinInstBank
- ALTA banka 2025 annual report (auditor's report), with page numbers in the
  `formula` column of the CSV. Figures that NBS forms do not contain (notes to the
  annual report, H1 2026 disclosure, shareholder assembly minutes) are constants in
  `signals.py` with a link to the source PDF and page.

## Recompute

```
python signals.py                      # or: uv run signals.py
python signals.py --cache nbs-csv --out signals.csv
```

NBS CSV files are cached in `--cache`, so reruns do not hit the network.

## License

MIT, same as the repository (see `LICENSE` in the root).
