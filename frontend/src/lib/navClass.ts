/** Стиль ссылки навигации. */
export const navClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-lg px-3 py-2 text-sm whitespace-nowrap ${isActive ? 'bg-blue-50 font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-200' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`
