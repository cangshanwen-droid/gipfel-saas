"use client"

import React, { createContext, useContext, useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { login as apiLogin } from "@/lib/api"

interface User {
  id: number
  username: string
  role: string
}

interface AuthContextType {
  user: User | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  loading: boolean
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const saved = localStorage.getItem("gipfel_auth")
    if (saved) {
      try {
        const { user: u, token: t } = JSON.parse(saved)
        setUser(u)
        setToken(t)
      } catch {}
    }
    setLoading(false)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password)
    setUser(res.user)
    setToken(res.token)
    localStorage.setItem("gipfel_auth", JSON.stringify({ user: res.user, token: res.token }))
    router.push("/dashboard")
  }, [router])

  const logout = useCallback(() => {
    setUser(null)
    setToken(null)
    localStorage.removeItem("gipfel_auth")
    router.push("/login")
  }, [router])

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
