# frozen_string_literal: true
#
# Validador de dos fases para eventcal/v1 usando json_schemer (draft 2020-12).
# Gemfile:  gem 'json_schemer'
#
# Fase 1: el documento completo contra el nucleo (esqueleto).
# Fase 2: el bloque `details` de cada evento contra el esquema de su `type`,
#         resuelto via registry.json. Tipo no registrado => solo esqueleto.
#
# Nota: en produccion esto vive en un service object de Rails
# (p.ej. app/services/eventcal/validator.rb), no como script suelto.

require 'json'
require 'json_schemer'
require 'pathname'

module Eventcal
  class Validator
    BASE = Pathname.new(__dir__)

    def initialize
      # format: true para que uri/date-time/date se asserten de verdad
      @core = JSONSchemer.schema(BASE.join('eventcal.schema.json'), format: true)
      @registry = JSON.parse(BASE.join('registry.json').read)['types']
      @ext = {} # cache de validadores de extension por type
    end

    # Devuelve [] si es valido, o [fase, mensaje] con el primer error.
    def validate(doc)
      # --- Fase 1: esqueleto contra el nucleo ---
      if (e = first_error(@core, doc))
        return ['fase 1 (nucleo)', e]
      end

      # --- Fase 2: details por tipo ---
      Array(doc['events']).each_with_index do |evt, i|
        type = evt['type']
        next if type.nil?
        next unless @registry.key?(type) # tipo desconocido: pasa solo el esqueleto

        if (e = first_error(extension_for(type), evt['details'] || {}))
          return ["fase 2 (#{type})", "events/#{i}/details#{e}"]
        end
      end

      [] # valido
    end

    def valid?(doc)
      validate(doc).empty?
    end

    private

    def extension_for(type)
      @ext[type] ||= JSONSchemer.schema(
        BASE.join(@registry[type]['file']), format: true
      )
    end

    # Primer error en formato "pointer: mensaje", o nil si valida.
    def first_error(schemer, data)
      err = schemer.validate(data).first
      err && "#{err['data_pointer']}: #{err['error']}"
    end
  end
end

# Uso de ejemplo:
# doc = JSON.parse(File.read('mi_calendario.json'))
# phase, msg = Eventcal::Validator.new.validate(doc)
# puts phase ? "rechazado en #{phase}: #{msg}" : 'valido'
