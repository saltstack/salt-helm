{{- define "salt-master.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "salt-master.fullname" -}}
{{- $name := include "salt-master.name" . -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else }}
{{- if .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name (include "salt-master.name" .) | trunc 63 | trimSuffix "-" -}}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end }}
{{- end }}
{{- end -}}

{{- define "salt-master.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "salt-master.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | default "" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "salt-master.selectorLabels" -}}
app.kubernetes.io/name: {{ include "salt-master.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}