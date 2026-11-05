package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/Neoforge-Labs/hephaestus/go/internal/compose"
	"github.com/Neoforge-Labs/hephaestus/go/internal/fragments"
	"github.com/Neoforge-Labs/hephaestus/go/internal/ingot"
)

const grafanaURL = "http://localhost:54300"

func newDevCmd(d Deps) *cobra.Command {
	dev := &cobra.Command{
		Use:   "dev",
		Short: "Run the ingot's local stack",
		Args:  cobra.NoArgs, // an unknown subcommand is a user error, not silent help
		RunE:  func(cmd *cobra.Command, _ []string) error { return cmd.Help() },
	}

	dev.AddCommand(&cobra.Command{
		Use:   "up",
		Short: "Start the local stack and wait until it is healthy",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return devRun(cmd.Context(), d, "up", true, nil)
		},
	})
	dev.AddCommand(&cobra.Command{
		Use:   "status",
		Short: "Show the local stack's services",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return devRun(cmd.Context(), d, "ps", false, nil)
		},
	})
	var volumes bool
	down := &cobra.Command{
		Use:   "down",
		Short: "Stop the local stack (keeps data unless --volumes)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			var extra []string
			if volumes {
				extra = []string{"-v"}
			}
			return devRun(cmd.Context(), d, "down", false, extra)
		},
	}
	down.Flags().BoolVar(&volumes, "volumes", false, "also delete the stack's data volumes")
	dev.AddCommand(down)
	return dev
}

// devRun loads the ingot, resolves its fragments, preflights the host and runs
// one compose verb. Order matters for exit codes: user mistakes (1) are
// reported before environment problems (2).
func devRun(ctx context.Context, d Deps, verb string, checkPorts bool, extra []string) error {
	cfg, err := ingot.Load(d.Dir)
	if err != nil {
		return &ExitError{ExitUser, err}
	}
	src := d.fragmentFS()
	frs, err := fragments.ResolveFrom(src, cfg.Dev.Fragments)
	if err != nil {
		return &ExitError{ExitUser, err}
	}
	if err := runDoctor(ctx, d); err != nil {
		return err
	}
	// Fragments live in a stable per-project directory, NOT os.MkdirTemp:
	// Compose bakes bind-mount source paths (objects.yaml mounts
	// ./seaweedfs-s3.json) into the containers, so a cleaned-up temp dir would
	// break restarts. Do not "simplify" this back to a temp dir.
	stateDir := filepath.Join(d.StateDir, cfg.Ingot.Name)
	files, err := fragments.Materialize(src, stateDir, frs)
	if err != nil {
		return envErr("writing fragments to %s: %v", stateDir, err)
	}
	if checkPorts {
		// `up` is idempotent: ports held by this project's own containers are
		// not collisions. Anything else holding a port still is.
		own := ownPorts(ctx, d, cfg.Ingot.Name, files)
		for _, f := range frs {
			for _, p := range f.Ports {
				if !own[p] && d.portInUse(p) {
					return envErr("port %d (fragment %q) is already in use by another process: stop it, or drop %q from dev.fragments", p, f.Name, f.Name)
				}
			}
		}
	}
	if err := d.Runner.Run(ctx, compose.Args(cfg.Ingot.Name, files, verb, extra...)); err != nil {
		return envErr("docker compose %s failed: %v", verb, err)
	}
	if verb == "up" && hasFragment(frs, "telemetry") {
		fmt.Fprintf(d.Out, "stack is up. Grafana: %s\n", grafanaURL)
	} else if verb == "up" {
		fmt.Fprintln(d.Out, "stack is up")
	}
	return nil
}

func hasFragment(frs []fragments.Fragment, name string) bool {
	for _, f := range frs {
		if f.Name == name {
			return true
		}
	}
	return false
}

// newSyncFragmentsCmd is a build-time helper for the moon task
// heph-cli:sync-fragments; hidden because it is not part of the user surface.
func newSyncFragmentsCmd(Deps) *cobra.Command {
	var check bool
	c := &cobra.Command{
		Use:    "sync-fragments <src> <dst>",
		Hidden: true,
		Args:   cobra.ExactArgs(2),
		RunE: func(_ *cobra.Command, a []string) error {
			if check {
				return fragments.Check(a[0], a[1])
			}
			return fragments.Sync(a[0], a[1])
		},
	}
	c.Flags().BoolVar(&check, "check", false, "fail if dst differs from src instead of copying")
	return c
}

// ownPorts returns the host ports published by this project's running
// containers. Failure to query means "none": the preflight then stays strict.
func ownPorts(ctx context.Context, d Deps, project string, files []string) map[int]bool {
	out, err := d.Runner.Output(ctx, compose.Args(project, files, "ps", "--format", "json"))
	if err != nil {
		return nil
	}
	type container struct {
		Publishers []struct {
			PublishedPort int
		}
	}
	var all []container
	trimmed := bytes.TrimSpace(out)
	if bytes.HasPrefix(trimmed, []byte("[")) { // older Compose: one JSON array
		_ = json.Unmarshal(trimmed, &all)
	} else { // newer Compose: one JSON object per line
		dec := json.NewDecoder(bytes.NewReader(trimmed))
		for {
			var c container
			if dec.Decode(&c) != nil {
				break
			}
			all = append(all, c)
		}
	}
	own := map[int]bool{}
	for _, c := range all {
		for _, p := range c.Publishers {
			if p.PublishedPort != 0 {
				own[p.PublishedPort] = true
			}
		}
	}
	return own
}
