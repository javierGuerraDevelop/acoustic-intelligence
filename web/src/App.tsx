import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

function App() {
  return (
    <main className="min-h-screen bg-background p-8">
      <Card className="mx-auto max-w-md">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Live Sound Radar</CardTitle>
            <Badge variant="secondary">Local</Badge>
          </div>

          <CardDescription>
            Local acoustic awareness dashboard
          </CardDescription>
        </CardHeader>

        <CardContent>
          <p className="text-sm text-muted-foreground">
            Frontend is running successfully.
          </p>
        </CardContent>

        <CardFooter>
          <Button>Start Listening</Button>
        </CardFooter>
      </Card>
    </main>
  )
}

export default App