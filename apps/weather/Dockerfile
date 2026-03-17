FROM python:3.12-slim                                                                                 
                                                                                                        
ENV PYTHONDONTWRITEBYTECODE=1                                                                         
ENV PYTHONUNBUFFERED=1                                                                                
ENV PORT=8080                                                                                         
                                                                                                        
WORKDIR /app                                                                                          
                                                                                                        
COPY requirements.txt .                                                                               
RUN pip install --no-cache-dir -r requirements.txt                                                    
                                                                                                       
COPY app.py .                                                                                         
COPY templates ./templates
COPY static ./static
                                                                                                       
EXPOSE 8080                                                                                           
                                                                                                        
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
