"""
infra — capa de RUNTIME/INFRA de Aleph (T8). NO contiene lógica de features:
es la base sobre la que corren. Provee:

  - jobs.py     : cola de trabajo DURABLE sobre Postgres (job_queue).
  - worker.py   : worker pool acotado que procesa la cola sin bloquear los requests.
  - run_handler : el handler 'puppet_run' que LLAMA al executor existente (no lo reescribe).
  - observability.py : Sentry + telemetría de runs + alerting (errores visibles).
  - infra_router.py  : endpoints aditivos (/v1/runs/enqueue, /v1/jobs, /health/deep).

Los runs encolados sobreviven reinicios (la cola es una tabla) y se reclaman al
bootear. La unidad durable es el JOB; cada ejecución produce su run en `runs`.
"""
