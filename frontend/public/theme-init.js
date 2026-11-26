// Ставит тёмную тему до отрисовки страницы, чтобы она не мигала белым.
;(function () {
  var choice = null
  try {
    choice = localStorage.getItem('buh.theme')
  } catch (error) {
    /* хранилище недоступно */
  }
  var dark =
    choice === 'dark' ||
    (choice !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
})()
