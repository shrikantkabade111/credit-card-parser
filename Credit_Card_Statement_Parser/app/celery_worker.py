# celery_worker.py 

"""
Celery worker entry point.
This ensures tasks are properly imported and registered.
"""

from app.tasks import celery_app, parse_statement_task

# Explicitly import task to register it
__all__ = ['celery_app', 'parse_statement_task']

if __name__ == '__main__':
    celery_app.start()
