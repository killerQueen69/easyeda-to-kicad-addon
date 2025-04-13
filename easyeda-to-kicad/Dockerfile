
FROM python:3.11-slim

RUN pip install flask easyeda2kicad

COPY easyeda_to_kicad.py /app.py

EXPOSE 7860

CMD ["python3", "/app.py"]
