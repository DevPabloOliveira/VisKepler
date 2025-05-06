// Cria uma função global para inicializar o mapa
window.createKeplerMap = function(config, csvData, geojsonData, additionalData = []) {
  console.log("createKeplerMap chamado com config:", config);
  
  // Monta o objeto de dados (keplerData) a partir das camadas definidas em config
  const keplerData = {};

  const layers = (config.config && config.config.visState && config.config.visState.layers) || [];
  layers.forEach((layer, i) => {
    const dataId = layer.config.dataId;
    if (dataId.includes("geojson")) {
      // Se não houver dados geojson, atribui um objeto vazio
      keplerData[dataId] = geojsonData || {};
    } else if (dataId.includes("csv")) {
      // Se não houver dados CSV, atribui um objeto vazio
      keplerData[dataId] = csvData || {};
    } else if (i >= 2 && i - 2 < additionalData.length) {
      keplerData[dataId] = additionalData[i - 2];
    } else {
      console.warn("Dados não encontrados para dataId:", dataId);
    }
  });
  
  // Verifica se window.KeplerGl está exportado como default
  let KeplerConstructor = window.KeplerGl;
  if (KeplerConstructor && KeplerConstructor.default) {
    KeplerConstructor = KeplerConstructor.default;
  }
  
  if (typeof KeplerConstructor !== "function") {
    console.error("KeplerGl constructor not found", window.KeplerGl);
    return;
  }
  
  try {
    // Cria a instância do mapa usando a configuração fornecida
    const keplerMap = new KeplerConstructor({
      container: "mapContainer",  // Elemento no qual o mapa será renderizado
      data: keplerData,
      options: config.config   // Configuração geral (visState, mapState, mapStyle)
    });
    console.log("Mapa kepler.gl inicializado com sucesso!");
  } catch (error) {
    console.error("Erro ao inicializar KeplerGl:", error);
  }
};
