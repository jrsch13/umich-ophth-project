import { useState } from 'react'
import { stationPost } from '../stationApi'

export default function InviteUsers() {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [invitation, setInvitation] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copyStatus, setCopyStatus] = useState('')

  async function create(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setInvitation(null)
    setCopyStatus('')
    try {
      setInvitation(await stationPost('/admin/invitations', { email: email.trim() }))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation.invitation_url)
      setCopyStatus('Link copied.')
    } catch {
      setCopyStatus('Select the invitation link and copy it manually.')
    }
  }

  return (
    <section className='card invite-card'>
      <button className='button secondary' type='button' aria-expanded={open} onClick={() => setOpen(!open)}>Invite Users</button>
      {open && (
        <>
          <form onSubmit={create}>
            <label className='field'><span>Resident email</span>
              <input type='email' required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
            <button className='button primary' type='submit' disabled={busy}>{busy ? 'Creating…' : 'Create Invitation'}</button>
          </form>
          {error && <p className='posture-load-error' role='alert'>{error}</p>}
          {invitation && (
            <>
              <p role='status'>Invitation created for {invitation.email}.</p>
              <label className='field'><span>Invitation link</span>
                <input readOnly value={invitation.invitation_url} onFocus={(event) => event.target.select()} />
              </label>
              <button className='button secondary' type='button' onClick={copy}>Copy Link</button>
              {copyStatus && <p role='status'>{copyStatus}</p>}
            </>
          )}
        </>
      )}
    </section>
  )
}
