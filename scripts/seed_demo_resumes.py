"""Create two fictional, unreviewed resumes without replacing existing documents."""
import argparse
import json
from urllib.request import Request, urlopen


def samples():
    for key, name, title, summary, skills, bullets in [
        ('sql', 'Alex Example', 'SQL analyst',
         'Fictional demo applicant. SQL data analyst interested in business intelligence, customer analytics, reporting and data quality.',
         'SQL, PostgreSQL, Python, pandas, Tableau, Power BI, Excel, statistics, A/B testing',
         ['Built a synthetic sales reporting project with SQL joins, window functions and data quality checks.',
          'Created dashboards to explain customer retention and revenue trends using fictional data.',
          'Documented metric definitions and experiment results for a mock business stakeholder.']),
        ('ml', 'Sam Example', 'ML engineer',
         'Fictional demo applicant. Machine learning engineer interested in predictive modelling, NLP, model evaluation and reliable deployment.',
         'Python, SQL, scikit-learn, PyTorch, NLP, machine learning, feature engineering, Docker, FastAPI, MLOps',
         ['Built a classification pipeline using synthetic data, with train/validation splits and leakage checks.',
          'Compared model precision and recall against a simple baseline and recorded experiment results.',
          'Packaged a model-serving API with FastAPI and Docker and tested input validation.']),
    ]:
        yield {'title': f'Demo — {title} (fictional)', 'template': 'modern',
               'content': {'name': name, 'email': f'{key}@example.invalid', 'phone': '',
                 'location': 'Singapore', 'summary': summary,
                 'sections': [
                   {'id': f'{key}-skills', 'title': 'Technical skills', 'entries': [
                     {'id': f'{key}-skills-entry', 'heading': 'Tools and methods', 'subheading': '', 'dates': '', 'bullets': [skills]}]},
                   {'id': f'{key}-projects', 'title': 'Demonstration projects', 'entries': [
                     {'id': f'{key}-project', 'heading': f'{title.title()} portfolio', 'subheading': 'Fictional learning project', 'dates': '2026', 'bullets': bullets}]},
                 ]}, 'layout': {'font_size': 11, 'margin': 18}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', choices=['alice', 'bob'], default='alice')
    parser.add_argument('--api', default='http://localhost:8000/v1')
    args = parser.parse_args()
    def call(path, body=None):
        request = Request(args.api.rstrip('/') + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'X-Dev-User': args.user, 'Content-Type': 'application/json'})
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    existing = {doc['title'] for doc in call('/documents?kind=resume')['items']}
    for sample in samples():
        if sample['title'] in existing:
            print('Kept existing:', sample['title'])
        else:
            call('/documents', sample)
            print('Created unreviewed:', sample['title'])


if __name__ == '__main__':
    main()
