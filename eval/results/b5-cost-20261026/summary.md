# B5 cost model: monthly cost by active users (USD, incl. 9% GST on AWS)

| | 10 users | 100 users | 1,000 users | 10,000 users | 100,000 users |
|---|---|---|---|---|---|
| API function | $0.02 | $0.24 | $2.42 | $24.19 | $242 |
| API Gateway | $0.00 | $0.03 | $0.25 | $2.54 | $25.38 |
| Aurora | $16.99 | $75.50 | $131 | $149 | $994 |
| AI and pipeline functions | $0.12 | $0.14 | $0.36 | $2.61 | $25.05 |
| S3 | $0.00 | $0.02 | $0.16 | $1.56 | $15.57 |
| CloudWatch Logs | $0.00 | $0.01 | $0.08 | $0.80 | $8.03 |
| Cognito | $0.00 | $0.00 | $0.00 | $0.00 | $495 |
| Amplify | $1.22 | $1.43 | $3.54 | $24.64 | $236 |
| Secrets and images | $1.61 | $1.61 | $1.61 | $1.61 | $1.61 |
| **Serverless AWS total** | **$21.76** | **$86.08** | **$152** | **$225** | **$2,226** |
| Aurora hours running / ACU | 84 h / 1.0 | 377 h / 1.0 | 654 h / 1.0 | 720 h / 1.0 | 720 h / 6.6 |
| LLM tokens at SoClaaS (NUS) | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |
| LLM tokens at Nova Lite price | $0.01 | $0.10 | $0.98 | $9.84 | $98.42 |
| LLM tokens at Claude Haiku 4.5 price | $0.14 | $1.39 | $13.89 | $139 | $1,389 |
| Always-on cloud, peak-sized | $669 | $670 | $672 | $700 | $1,517 |
| Always-on cloud, minimum | $174 | $174 | $177 | $205 | $1,022 |
| On-premise server | $741 | $741 | $744 | $772 | $1,589 |

On-premise parts (10,000 users): hardware (3-year) $250, power and cooling $66.72, network $209, admin time $212, hosted services kept $34.03.

Break-even (serverless stops being cheaper): Break-even vs always-on minimum: about 4,467 users; Break-even vs peak-sized: about 50,119 users; Break-even vs on-premise: about 56,234 users.

Capacity note: the deployed limits serve about 10.7 browse requests/s (B3 run 1); at the usage above, 10,000 active users peak at about 3.5 req/s, and 100,000 at about 35 req/s, which needs the raised limits of B3 run 2 or more.
