package compose

import (
	"reflect"
	"testing"
)

func TestArgs(t *testing.T) {
	files := []string{"/f/a.yaml", "/f/b.yaml"}
	head := []string{"compose", "-p", "hello", "-f", "/f/a.yaml", "-f", "/f/b.yaml"}
	cases := []struct {
		name  string
		verb  string
		extra []string
		tail  []string
	}{
		{"up detaches and waits", "up", nil, []string{"up", "-d", "--wait"}},
		{"ps takes no flags", "ps", nil, []string{"ps"}},
		{"down keeps volumes", "down", nil, []string{"down"}},
		{"down -v only when asked", "down", []string{"-v"}, []string{"down", "-v"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := Args("hello", files, c.verb, c.extra...)
			want := append(append([]string{}, head...), c.tail...)
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("got  %v\nwant %v", got, want)
			}
		})
	}
}

func TestArgsUpExactBriefValue(t *testing.T) {
	got := Args("hello", []string{"/f/a.yaml", "/f/b.yaml"}, "up")
	want := []string{"compose", "-p", "hello", "-f", "/f/a.yaml", "-f", "/f/b.yaml", "up", "-d", "--wait"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v", got)
	}
}
