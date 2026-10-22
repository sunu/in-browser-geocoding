export interface Decision<T> { value: T; confidence: number; impl: string; trace: Record<string, any> }
export interface Candidate { id: string; name: string; source: "overture" | "photon"; subtype: string | null; description: string; score: number; ancestors: string[] }
