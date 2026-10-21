from mangum import Mangum
from job_hunter.api.main import app

handler = Mangum(app, lifespan="off")
