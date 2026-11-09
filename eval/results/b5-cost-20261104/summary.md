# B5 cost model: monthly cost by active users (USD, incl. 9% GST on AWS)

| | 10 users | 100 users | 1,000 users | 10,000 users | 100,000 users |
|---|---|---|---|---|---|
| API function | $0.05 | $0.50 | $5.03 | $50.30 | $503 |
| API Gateway | $0.00 | $0.03 | $0.25 | $2.54 | $25.38 |
| Aurora | $8.46 | $37.95 | $69.63 | $118 | $531 |
| AI and pipeline functions | $0.64 | $0.66 | $0.88 | $3.04 | $24.64 |
| S3 | $0.00 | $0.02 | $0.16 | $1.56 | $15.57 |
| CloudWatch Logs | $0.00 | $0.01 | $0.08 | $0.80 | $8.03 |
| Cognito | $0.00 | $0.00 | $0.00 | $0.00 | $495 |
| Amplify | $1.22 | $1.43 | $3.54 | $24.64 | $236 |
| Secrets and images | $1.61 | $1.61 | $1.61 | $1.61 | $1.61 |
| **Serverless AWS total** | **$13.06** | **$46.00** | **$88.49** | **$221** | **$2,005** |
| Aurora hours running / ACU | 84 h / 0.5 | 377 h / 0.5 | 654 h / 0.53 | 720 h / 0.79 | 720 h / 3.38 |
| LLM tokens at SoClaaS (NUS) | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |
| LLM tokens at Nova Lite price | $0.01 | $0.10 | $0.96 | $9.59 | $95.90 |
| LLM tokens at Claude Haiku 4.5 price | $0.14 | $1.36 | $13.56 | $136 | $1,356 |
| Always-on cloud, peak-sized | $1,333 | $1,333 | $1,336 | $1,364 | $2,180 |
| Always-on cloud, minimum | $175 | $175 | $178 | $205 | $1,021 |
| On-premise server | $741 | $742 | $744 | $772 | $1,588 |

On-premise parts (10,000 users): hardware (3-year) $250, power and cooling $66.72, network $209, admin time $212, hosted services kept $34.50.

Break-even (serverless stops being cheaper): Break-even vs always-on minimum: about 8,913 users; Break-even vs peak-sized: not within 100,000 users; Break-even vs on-premise: about 63,096 users.

Capacity note: the deployed limits serve about 10.7 browse requests/s (B3 run 1); at the usage above, 10,000 active users peak at about 3.5 req/s, and 100,000 at about 35 req/s, which needs the raised limits of B3 run 2 or more.
