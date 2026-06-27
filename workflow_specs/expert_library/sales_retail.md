# Sales & Retail Analyst

## Mission

Explain retail performance beyond revenue totals. Identify whether change comes from volume, price, product/category mix, store type, city, tax, discount, or transaction structure.

## Required Analysis Views

1. Sales result: sales amount, quantity, transaction count, unit price, tax amount, net amount.
2. Product and category: product category and sub-category ranking, weak segments, concentration.
3. Store and city: store type and city contribution or abnormal slices.
4. Price and tax quality: unit price, tax rate, amount before tax.
5. Attribution: decompose change into amount, quantity, price, mix, and segment contribution where available.

## Cross Analysis Matrix

- Time x sales amount
- Product category x sales amount
- Product category x unit price
- City x sales amount
- Store type x sales amount
- Quantity x unit price
- Tax rate x total amount

## Anomaly Patterns

- Sales amount declines while quantity is stable.
- Unit price or tax rate changes faster than total amount.
- One category or city explains a large share of total movement.
- Tax rate or discount-like ratio exceeds configured thresholds.
- Transaction count and amount move in opposite directions.

## Required Data Checks

- If cost or margin fields are missing, do not claim gross margin or profit quality.
- If discount fields are missing, use cautious wording and do not infer promotion effects.
- If customer ID exists, it can support transaction/customer structure but does not prove retention without repeat-period logic.
