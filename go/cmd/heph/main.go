// Command heph is the Hephaestus CLI.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"

	"github.com/Neoforge-Labs/hephaestus/go/internal/cli"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	deps, err := cli.DefaultDeps()
	if err != nil {
		fmt.Fprintf(os.Stderr, "heph: %v\n", err)
		os.Exit(cli.ExitEnv)
	}
	code := cli.Execute(ctx, deps, os.Args[1:])
	stop()
	os.Exit(code)
}
