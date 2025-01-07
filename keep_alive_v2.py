from fastapi import FastAPI

app = FastAPI()


@app.api_route('/', methods=['GET', 'HEAD'])
async def read_root():
    return {"message": "App is Running..."}
