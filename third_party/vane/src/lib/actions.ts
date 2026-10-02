export const getSuggestions = async (chatHistory: [string, string][]) => {
  const chatModel = localStorage.getItem('chatModelKey');
  const chatModelProvider = localStorage.getItem('chatModelProviderId');

  const res = await fetch(`/api/suggestions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      chatHistory,
      chatModel: {
        providerId: chatModelProvider,
        key: chatModel,
      },
    }),
  });

  const data = (await res.json()) as { suggestions: string[] };

  return data.suggestions;
};

/*
 * [Aleph · Gate 4 · Fase 6 · §6.a.bis] LA FUGA MÁS CARA DEL STACK, CORTADA.
 *
 * El original mandaba la IP del usuario a `free.freeipapi.com` —un tercero— para adivinar
 * su ciudad y pintar el clima. Es la única llamada del árbol que expone al USUARIO en vez
 * de a su consulta, y estaba en un producto que se vende como privado.
 *
 * No se reemplaza por otro proveedor: se apaga. Las tres claves salen `undefined`, que es
 * lo que el llamador ya tenía que saber manejar. Nada se rellena: una ubicación inventada
 * sería peor que no tenerla.
 *
 * NOTA DE FORMA: se conservan la firma y las tres claves exactas del original, con sus
 * mismos tipos inferidos. Devolver `null` habría sido más limpio de leer y habría roto el
 * typecheck de `next build` en `WeatherWidget.tsx:54,57,60`, que las desestructura. Ley 5:
 * cero refactor — se corta la red, no la forma.
 *
 * Si algún día la Sala quiere clima local, la ubicación la pone el usuario o la pone el
 * sistema operativo con su permiso — jamás un tercero adivinando por IP.
 */
export const getApproxLocation = async () => {
  const data: any = {};

  return {
    latitude: data.latitude,
    longitude: data.longitude,
    city: data.cityName,
  };
};
