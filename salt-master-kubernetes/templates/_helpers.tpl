{{- define "salt-master-kubernetes.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "salt-master-kubernetes.fullname" -}}
{{- $name := include "salt-master-kubernetes.name" . -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else }}
{{- if .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name (include "salt-master-kubernetes.name" .) | trunc 63 | trimSuffix "-" -}}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end }}
{{- end }}
{{- end -}}

{{- define "salt-master-kubernetes.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "salt-master-kubernetes.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | default "" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "salt-master-kubernetes.selectorLabels" -}}
app.kubernetes.io/name: {{ include "salt-master-kubernetes.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}