// Package fragments resolves the Compose fragments an ingot selects and reads
// their host ports from the fragment files themselves. Maturity: experimental.
package fragments

import (
	"embed"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// files is the copy of compose/ produced by `moon run heph-cli:sync-fragments`.
// It is COMMITTED, not gitignored: go:embed reads the source tree, and the
// module zip the Go proxy serves is the git tree, so a `go install`ed or
// release-built heph gets exactly what is in version control. While it was
// ignored, every binary built from a clean checkout embedded nothing and told
// its user to run a moon task they do not have. `heph-cli:check-fragments`
// (and TestEmbeddedCopyMatchesCompose) is the gate that keeps this copy and
// compose/ identical; emptying the directory is now a compile error rather
// than a silent empty embed, since go:embed rejects a directory with no
// embeddable files.
//
//go:embed all:files
var embedded embed.FS

// Fragment is one selected Compose fragment.
type Fragment struct {
	Name  string // "telemetry"
	Path  string // path within the fragment filesystem, "telemetry.yaml"
	Ports []int  // host ports published by any service, ascending
}

// Embedded returns the embedded fragment filesystem.
func Embedded() fs.FS {
	sub, err := fs.Sub(embedded, "files")
	if err != nil {
		return embedded // unreachable: "files" is always embedded
	}
	return sub
}

// Resolve looks names up in the embedded fragments.
func Resolve(names []string) ([]Fragment, error) { return ResolveFrom(Embedded(), names) }

// ResolveFrom looks names up in fsys, where each fragment is <name>.yaml.
func ResolveFrom(fsys fs.FS, names []string) ([]Fragment, error) {
	avail, err := Available(fsys)
	if err != nil {
		return nil, err
	}
	if len(avail) == 0 {
		return nil, fmt.Errorf("no fragments are embedded in this heph build: run `moon run heph-cli:sync-fragments` and rebuild")
	}
	have := map[string]bool{}
	for _, a := range avail {
		have[a] = true
	}
	out := make([]Fragment, 0, len(names))
	for _, n := range names {
		if !have[n] {
			return nil, fmt.Errorf("unknown fragment %q; available: %s", n, strings.Join(avail, ", "))
		}
		p := n + ".yaml"
		ports, err := parsePorts(fsys, p)
		if err != nil {
			return nil, err
		}
		out = append(out, Fragment{Name: n, Path: p, Ports: ports})
	}
	return out, nil
}

// Available lists fragment names (the *.yaml files in fsys), sorted.
func Available(fsys fs.FS) ([]string, error) {
	ents, err := fs.ReadDir(fsys, ".")
	if err != nil {
		return nil, fmt.Errorf("reading fragments: %w", err)
	}
	var names []string
	for _, e := range ents {
		if !e.IsDir() && path.Ext(e.Name()) == ".yaml" {
			names = append(names, strings.TrimSuffix(e.Name(), ".yaml"))
		}
	}
	sort.Strings(names)
	return names, nil
}

type composeFile struct {
	Services map[string]struct {
		Ports []yaml.Node `yaml:"ports"`
	} `yaml:"services"`
}

func parsePorts(fsys fs.FS, p string) ([]int, error) {
	raw, err := fs.ReadFile(fsys, p)
	if err != nil {
		return nil, fmt.Errorf("reading fragment %s: %w", p, err)
	}
	var cf composeFile
	if err := yaml.Unmarshal(raw, &cf); err != nil {
		return nil, fmt.Errorf("fragment %s is not valid YAML: %w", p, err)
	}
	set := map[int]bool{}
	for svc, s := range cf.Services {
		for i := range s.Ports {
			host, err := hostPort(&s.Ports[i])
			if err != nil {
				return nil, fmt.Errorf("fragment %s, service %s: %w", p, svc, err)
			}
			if host != 0 {
				set[host] = true
			}
		}
	}
	ports := make([]int, 0, len(set))
	for h := range set {
		ports = append(ports, h)
	}
	sort.Ints(ports)
	return ports, nil
}

// hostPort extracts the published host port from one `ports:` entry. 0 means
// the entry publishes no fixed host port (container-only, so Docker picks one).
func hostPort(n *yaml.Node) (int, error) {
	switch n.Kind {
	case yaml.ScalarNode:
		parts := strings.Split(n.Value, ":")
		var h string
		switch len(parts) {
		case 1:
			return 0, nil
		case 2:
			h = parts[0]
		case 3:
			h = parts[1] // ip:host:container
		default:
			return 0, fmt.Errorf("unsupported port mapping %q", n.Value)
		}
		v, err := strconv.Atoi(h)
		if err != nil || v < 1 || v > 65535 {
			return 0, fmt.Errorf("unsupported host port %q in mapping %q (need a literal port number)", h, n.Value)
		}
		return v, nil
	case yaml.MappingNode:
		var long struct {
			Published string `yaml:"published"`
		}
		if err := n.Decode(&long); err != nil {
			return 0, fmt.Errorf("unsupported port entry: %w", err)
		}
		if long.Published == "" {
			return 0, nil
		}
		v, err := strconv.Atoi(long.Published)
		if err != nil || v < 1 || v > 65535 {
			return 0, fmt.Errorf("unsupported published port %q", long.Published)
		}
		return v, nil
	}
	return 0, fmt.Errorf("unsupported ports entry on line %d", n.Line)
}

// Materialize makes dir hold exactly fsys's files (the fragments and the support
// files they bind-mount, like seaweedfs-s3.json) and returns the absolute paths
// of the selected fragments, in order.
//
// dir is hephkit's alone — `<os.UserCacheDir>/heph/stacks/<project>`, written by
// nothing else — so a top-level file that is not in fsys is one this function
// wrote under an earlier heph whose fragment set has since changed. It is
// deleted: left behind, a renamed or dropped fragment sits in the stack
// directory looking current, and the next person debugging the stack has to
// work out which files Compose was actually given.
//
// Writes happen before deletions, so a failed write leaves the previous good
// state in place rather than a half-emptied directory. Subdirectories are never
// touched. Callers must keep calling this before querying Compose for the
// project's own containers: `docker compose ps -f ...` needs the files on disk.
func Materialize(fsys fs.FS, dir string, selected []Fragment) ([]string, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	ents, err := fs.ReadDir(fsys, ".")
	if err != nil {
		return nil, err
	}
	ours := make(map[string]bool, len(ents))
	for _, e := range ents {
		if e.IsDir() {
			continue
		}
		b, err := fs.ReadFile(fsys, e.Name())
		if err != nil {
			return nil, err
		}
		if err := os.WriteFile(filepath.Join(dir, e.Name()), b, 0o644); err != nil {
			return nil, err
		}
		ours[e.Name()] = true
	}
	if err := prune(dir, ours); err != nil {
		return nil, err
	}
	paths := make([]string, len(selected))
	for i, f := range selected {
		paths[i] = filepath.Join(dir, f.Path)
	}
	return paths, nil
}

// prune removes every top-level file in dir that is not in keep.
func prune(dir string, keep map[string]bool) error {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, e := range ents {
		if e.IsDir() || keep[e.Name()] {
			continue
		}
		if err := os.Remove(filepath.Join(dir, e.Name())); err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("removing stale fragment %s: %w", e.Name(), err)
		}
	}
	return nil
}
