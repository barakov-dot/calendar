import { Link } from 'react-router'

import { PlusIcon } from './Icons'

/** Круглая кнопка «добавить» в углу экрана. */
export default function AddButton({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      aria-label={label}
      title={label}
      className="fixed right-4 bottom-24 z-30 flex size-14 items-center justify-center rounded-2xl bg-blue-700 text-white shadow-lg hover:bg-blue-800 lg:right-6 lg:bottom-6"
    >
      <PlusIcon className="size-7" />
    </Link>
  )
}
