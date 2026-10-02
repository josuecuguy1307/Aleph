# Memoria {#memoria}

Un agente no es un modelo pelado: recuerda lo que ha venido haciendo y lo que
sabe de ti, entre tareas. Pero **tú** decides cuánto arrastra y qué queda fijado.

## Recordar o arrancar de cero {#recordar}

- **Recuerda entre corridas:** conserva lo que ha venido haciendo y lo que sabe
  de ti, de una tarea a la otra.
- **Arranca de cero:** no guarda nada entre tareas. Cada corrida empieza limpia.

## Herencia — qué se lleva a cada copia {#herencia}

Cuando reusas o compones un agente, decides qué **hereda**:

- **Solo la pericia:** opera desde su pericia y lo que le pediste recordar; su
  experiencia auto-aprendida de cada corrida **no se acumula**. Rige en cada
  corrida y al reusarlo o componerlo.
- **Todo lo que sabe:** conserva todo lo que aprende — pericia y experiencia.

En ambos casos, la **memoria de cuenta y lo confidencial nunca se arrastran**.
Guardas el agente para **fijar** la herencia elegida.

## Memoria de cuenta — "Sobre ti" {#cuenta}

Es lo que tus agentes saben de ti. Lo revisas y lo podas cuando quieras. Cuando
un agente aprende algo sobre ti, **te lo propone**: no rige hasta tu OK. Lo
encuentras en el panel "Sobre ti" del Cuarto y también en la Sala. Cuando lo
guardas, tus agentes ya lo saben; cuando lo podas, deja de regir.

## Memoria compartida del cuarto {#compartida}

En un cuarto con varios agentes conectados hay una **base de conocimiento
compartida** (entidades + relaciones) que todos leen y escriben. Vive en el
espacio del run; los sub-agentes la ven por el mismo archivo real. Cada agente
conectado deja su aporte al terminar. Una pieza puede estar **aislada**: no ve ni
deja nada en esa memoria compartida.

## Conocimiento de referencia (RAG) {#rag}

Son documentos que el agente lee como **apuntes de referencia**, nunca como
órdenes. El índice vive en tu máquina y los embeddings usan **tu** llave.
